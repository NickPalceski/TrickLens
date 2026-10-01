"""Step 6a: the worker's ffmpeg media pipeline.

Needs ffmpeg, so it only really runs in the worker image
(`make test-worker`, and CI's worker-image step). In the API image, where
`make test` runs, every test here skips.

Input clips are generated on the fly with ffmpeg's lavfi test sources
(testsrc2 video, sine audio), so there are no binary fixtures to commit.
The worker tests at the bottom run against the same real Postgres and
LocalStack S3 as test_clips.py.
"""

import os
import shutil
import subprocess
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.analyzer import media
from app.config import get_settings
from app.db import SessionLocal
from app.models.clip import Analysis, Clip
from app.models.enums import ClipStatus
from app.models.user import User
from app.services.storage import get_storage

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg not installed — run in the worker image: make test-worker",
)


def _make_clip(
    path: str,
    *,
    size: str = "1920x1080",
    fps: int = 60,
    seconds: float = 2,
    audio: bool = True,
    rotation: int | None = None,
) -> str:
    cmd = ["ffmpeg", "-y", "-v", "error"]
    cmd += ["-f", "lavfi", "-i", f"testsrc2=size={size}:rate={fps}:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd.append(path)
    subprocess.run(cmd, check=True, capture_output=True)

    if rotation is not None:
        # A phone clip shot in portrait is stored landscape plus a display
        # rotation, not as portrait pixels. Reproduce that exactly.
        rotated = path.replace(".mp4", "-rot.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-display_rotation:v:0", str(rotation),
             "-i", path, "-c", "copy", rotated],
            check=True,
            capture_output=True,
        )  # fmt: skip
        return rotated
    return path


def _transcode(tmp_path, src: str) -> media.VideoInfo:
    """Run probe -> transcode, then probe the *output* and return that."""
    out = str(tmp_path / "out.mp4")
    media.transcode(src, out, media.probe(src))
    return media.probe(out)


# --- probe -------------------------------------------------------------------


def test_probe_reads_real_duration_and_fps(tmp_path):
    info = media.probe(_make_clip(str(tmp_path / "in.mp4"), fps=60, seconds=2))
    assert info.fps == pytest.approx(60, abs=0.01)
    assert info.duration_ms == pytest.approx(2000, abs=50)
    assert (info.width, info.height) == (1920, 1080)


def test_probe_caps_duration_at_30s(tmp_path):
    src = _make_clip(str(tmp_path / "long.mp4"), size="320x240", fps=10, seconds=35, audio=False)
    assert media.probe(src).duration_ms == 30_000


def test_probe_rejects_non_video(tmp_path):
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"fake video bytes")
    with pytest.raises(media.MediaError) as e:
        media.probe(str(junk))
    assert e.value.reason == "unreadable video file"


def test_probe_rejects_audio_only(tmp_path):
    path = str(tmp_path / "audio.m4a")
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=duration=2", path],
        check=True,
        capture_output=True,
    )
    with pytest.raises(media.MediaError) as e:
        media.probe(path)
    assert e.value.reason == "no video stream found"


def test_probe_rejects_too_short(tmp_path):
    src = _make_clip(str(tmp_path / "blip.mp4"), seconds=0.2, audio=False)
    with pytest.raises(media.MediaError) as e:
        media.probe(src)
    assert e.value.reason == "clip too short"


# --- transcode ---------------------------------------------------------------


def test_transcode_landscape_to_720p_keeps_fps(tmp_path):
    out = _transcode(tmp_path, _make_clip(str(tmp_path / "in.mp4"), size="1920x1080", fps=60))
    assert (out.width, out.height) == (1280, 720)
    assert out.fps == pytest.approx(60, abs=0.01)


def test_transcode_portrait_short_side_is_720(tmp_path):
    out = _transcode(tmp_path, _make_clip(str(tmp_path / "in.mp4"), size="1080x1920", fps=30))
    assert (out.width, out.height) == (720, 1280)
    assert out.fps == pytest.approx(30, abs=0.01)


def test_transcode_applies_phone_rotation(tmp_path):
    """Landscape pixels + a 90° display rotation must come out upright
    (portrait), with no rotation metadata left for players to re-apply."""
    src = _make_clip(str(tmp_path / "in.mp4"), size="1920x1080", rotation=90)
    out = _transcode(tmp_path, src)
    assert (out.width, out.height) == (720, 1280)


def test_transcode_never_upscales(tmp_path):
    out = _transcode(tmp_path, _make_clip(str(tmp_path / "in.mp4"), size="640x360"))
    assert (out.width, out.height) == (640, 360)


def test_transcode_caps_output_fps_but_probe_keeps_source_fps(tmp_path):
    src = _make_clip(str(tmp_path / "in.mp4"), size="640x360", fps=120, audio=False)
    assert media.probe(src).fps == pytest.approx(120, abs=0.01)
    assert _transcode(tmp_path, src).fps == pytest.approx(media.MAX_OUTPUT_FPS, abs=0.01)


def test_transcode_caps_length_at_30s(tmp_path):
    src = _make_clip(str(tmp_path / "long.mp4"), size="320x240", fps=10, seconds=35, audio=False)
    assert _transcode(tmp_path, src).duration_ms <= 30_100


def test_thumbnail_writes_a_jpeg(tmp_path):
    src = _make_clip(str(tmp_path / "in.mp4"), size="640x360")
    thumb = str(tmp_path / "thumb.jpg")
    media.thumbnail(src, thumb, at_ms=1000)
    with open(thumb, "rb") as f:
        assert f.read(3) == b"\xff\xd8\xff"  # JPEG magic


# --- worker, end to end (real Postgres + LocalStack S3) -----------------------

needs_real_worker = pytest.mark.skipif(
    get_settings().analyzer != "real", reason="worker image only (ANALYZER=real)"
)


async def _queued_clip_with_upload(local_path: str) -> uuid.UUID:
    clip_id = uuid.uuid4()
    s3_key = f"raw/{clip_id}.mp4"
    await get_storage().upload(local_path, s3_key, "video/mp4")
    async with SessionLocal() as db:
        user = User(cognito_sub=f"test-{uuid.uuid4()}", username=f"m{uuid.uuid4().hex[:10]}")
        db.add(user)
        await db.flush()
        db.add(
            Clip(
                id=clip_id,
                user_id=user.id,
                status=ClipStatus.QUEUED,
                s3_key=s3_key,
                # Deliberately wrong, as a client could send: the worker must
                # overwrite both with what ffprobe actually reads.
                duration_ms=9999,
                source_fps=24,
            )
        )
        await db.commit()
    return clip_id


async def _load(clip_id: uuid.UUID) -> tuple[Clip, list[Analysis]]:
    from sqlalchemy import select

    async with SessionLocal() as db:
        clip = await db.scalar(select(Clip).where(Clip.id == clip_id))
        analyses = list(await db.scalars(select(Analysis).where(Analysis.clip_id == clip_id)))
    return clip, analyses


@needs_real_worker
@pytest.mark.asyncio(loop_scope="session")
async def test_worker_writes_processed_and_thumb_and_verifies_metadata(tmp_path):
    from app import worker

    clip_id = await _queued_clip_with_upload(
        _make_clip(str(tmp_path / "in.mp4"), size="1920x1080", fps=60, seconds=2)
    )
    await worker._process_message({"clip_id": str(clip_id)})

    clip, analyses = await _load(clip_id)
    assert clip.processed_key == f"processed/{clip_id}.mp4"
    assert clip.thumb_key == f"thumbs/{clip_id}.jpg"
    assert clip.source_fps == 60
    assert clip.duration_ms == pytest.approx(2000, abs=50)
    assert len(analyses) == 1

    storage = get_storage()
    processed = await storage.head(clip.processed_key)
    thumb = await storage.head(clip.thumb_key)
    assert processed is not None and processed["ContentType"] == "video/mp4"
    assert thumb is not None and thumb["ContentType"] == "image/jpeg"

    # And the processed file is really the 720p transcode, not a copy.
    local = os.path.join(tmp_path, "check.mp4")
    await storage.download(clip.processed_key, local)
    out = media.probe(local)
    assert (out.width, out.height) == (1280, 720)


@needs_real_worker
@pytest.mark.asyncio(loop_scope="session")
async def test_worker_marks_unreadable_upload_unanalyzable(tmp_path):
    from app import worker

    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"fake video bytes")
    clip_id = await _queued_clip_with_upload(str(junk))
    await worker._process_message({"clip_id": str(clip_id)})

    clip, analyses = await _load(clip_id)
    assert clip.status == ClipStatus.UNANALYZABLE
    assert clip.processed_key is None
    assert [a.failure_reason for a in analyses] == ["unreadable video file"]


async def _set_analyzing(clip_id: uuid.UUID, since: datetime) -> None:
    async with SessionLocal() as db:
        clip = await db.get(Clip, clip_id)
        clip.status = ClipStatus.ANALYZING
        clip.updated_at = since  # explicit, so onupdate=now() doesn't apply
        await db.commit()


@needs_real_worker
@pytest.mark.asyncio(loop_scope="session")
async def test_worker_reclaims_a_clip_whose_run_died(tmp_path):
    """A Lambda timeout mid-analysis leaves the clip `analyzing`. Once its
    lease has expired, SQS's redelivery must reprocess it, not skip it."""
    from app import worker

    clip_id = await _queued_clip_with_upload(
        _make_clip(str(tmp_path / "in.mp4"), size="640x360", seconds=1, audio=False)
    )
    stale = datetime.now(UTC) - worker.ANALYZING_LEASE - timedelta(seconds=30)
    await _set_analyzing(clip_id, since=stale)

    await worker._process_message({"clip_id": str(clip_id)})

    clip, _ = await _load(clip_id)
    assert clip.status in (ClipStatus.ANALYZED, ClipStatus.UNANALYZABLE)  # stub scorer's 10%
    assert clip.processed_key is not None


@needs_real_worker
@pytest.mark.asyncio(loop_scope="session")
async def test_worker_leaves_a_live_run_alone(tmp_path):
    """A duplicate delivery while another run holds the lease must skip,
    not process the same clip concurrently."""
    from app import worker

    clip_id = await _queued_clip_with_upload(
        _make_clip(str(tmp_path / "in.mp4"), size="640x360", seconds=1, audio=False)
    )
    await _set_analyzing(clip_id, since=datetime.now(UTC))

    await worker._process_message({"clip_id": str(clip_id)})

    clip, analyses = await _load(clip_id)
    assert clip.status == ClipStatus.ANALYZING
    assert clip.processed_key is None
    assert analyses == []
