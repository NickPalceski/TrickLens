"""ffprobe/ffmpeg wrappers: verify, normalize and thumbnail an uploaded clip.

Step 6a. Plain subprocess calls, no Python video bindings: the static
ffmpeg/ffprobe binaries Dockerfile.worker copies in are the whole
dependency. Every function here is blocking; the worker calls them through
asyncio.to_thread.

Anything wrong with the *file itself* raises MediaError with a reason
specific enough to show the user as-is (it becomes Analysis.failure_reason),
same fail-safe rule as the scorer: never guess, say what's wrong. Anything
else (ffmpeg missing, a timeout) is a plain exception, and the worker lets
SQS retry it.
"""

import json
import subprocess
from dataclasses import dataclass
from fractions import Fraction

# Clips are capped at 30s (ClipCreate validates the client-reported
# duration; this enforces it on the actual file).
MAX_DURATION_S = 30
# Output short side. A portrait phone clip becomes 720x1280, a landscape one
# 1280x720. Never upscaled.
TARGET_SHORT_SIDE = 720
# Output frame-rate cap. 60fps covers what 6b/6c need (a flip is ~6 frames
# at 60) while keeping 120/240fps slow-mo files a sane size for playback.
# source_fps still records the real source rate.
MAX_OUTPUT_FPS = 60
# A clip shorter than this can't contain a pop and a landing.
MIN_DURATION_MS = 500

_PROBE_TIMEOUT_S = 30
_TRANSCODE_TIMEOUT_S = 240


class MediaError(Exception):
    """The uploaded file itself is the problem. `reason` is user-facing."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class VideoInfo:
    duration_ms: int  # capped at MAX_DURATION_S — what the processed file will contain
    fps: float  # real source rate, not the capped output rate
    width: int
    height: int

    @property
    def output_fps(self) -> int:
        return min(round(self.fps), MAX_OUTPUT_FPS)


def _parse_rate(rate: str | None) -> float:
    """ffprobe reports rates as fractions ("60000/1001"); "0/0" means unknown."""
    if not rate or rate == "0/0":
        return 0.0
    return float(Fraction(rate))


def probe(path: str) -> VideoInfo:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=avg_frame_rate,r_frame_rate,width,height:format=duration",
            "-of", "json",
            path,
        ],
        capture_output=True,
        text=True,
        timeout=_PROBE_TIMEOUT_S,
    )  # fmt: skip
    if proc.returncode != 0:
        raise MediaError("unreadable video file")

    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams") or []
    if not streams:
        raise MediaError("no video stream found")
    stream = streams[0]

    # avg_frame_rate is the honest number for phone footage, which is
    # usually variable-frame-rate; r_frame_rate is the fallback when a
    # container doesn't report an average.
    fps = _parse_rate(stream.get("avg_frame_rate")) or _parse_rate(stream.get("r_frame_rate"))
    try:
        duration_s = float(data.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        raise MediaError("unreadable video file") from None
    if fps <= 0:
        raise MediaError("unreadable video file")

    duration_ms = min(round(duration_s * 1000), MAX_DURATION_S * 1000)
    if duration_ms < MIN_DURATION_MS:
        raise MediaError("clip too short")

    return VideoInfo(
        duration_ms=duration_ms,
        fps=fps,
        width=int(stream.get("width") or 0),
        height=int(stream.get("height") or 0),
    )


def _scale_filter() -> str:
    """Short side -> TARGET_SHORT_SIDE (never upscaled), long side follows
    the aspect ratio. -2 keeps it even, which libx264's yuv420p requires.
    ffmpeg auto-rotates before filtering, so iw/ih here are already the
    upright dimensions of a phone clip with rotation metadata."""
    short = f"trunc(min({TARGET_SHORT_SIDE}\\,{{d}})/2)*2"
    w = f"if(gte(iw\\,ih)\\,-2\\,{short.format(d='iw')})"
    h = f"if(gte(iw\\,ih)\\,{short.format(d='ih')}\\,-2)"
    return f"scale=w={w}:h={h}"


def transcode(src: str, dst: str, info: VideoInfo) -> None:
    """Normalize to H.264/AAC MP4: 720p short side, constant frame rate at
    the (capped) source rate, capped at 30s, faststart for streaming.

    Constant frame rate matters for later steps: 6b/6c turn frame indices
    into milliseconds, which is only valid if frames are evenly spaced, and
    phone footage usually isn't.
    """
    proc = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v", "error",
            "-i", src,
            "-t", str(MAX_DURATION_S),
            "-map", "0:v:0",
            "-map", "0:a:0?",  # keep the first audio track if there is one
            "-vf", f"{_scale_filter()},fps={info.output_fps}",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            dst,
        ],
        capture_output=True,
        text=True,
        timeout=_TRANSCODE_TIMEOUT_S,
    )  # fmt: skip
    if proc.returncode != 0:
        # probe() already accepted the file, so a decode failure here means
        # it's corrupt partway through, which is still the file's fault.
        raise MediaError("unreadable video file")


def thumbnail(src: str, dst: str, at_ms: int) -> None:
    """One JPEG frame from the *processed* file (already upright and 720p).

    The worker picks `at_ms`: the apex of the biggest pop Stage A found
    (6b), or the middle of the clip if it found none.
    """
    proc = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v", "error",
            "-ss", f"{at_ms / 1000:.3f}",
            "-i", src,
            "-frames:v", "1",
            "-q:v", "3",
            dst,
        ],
        capture_output=True,
        text=True,
        timeout=_PROBE_TIMEOUT_S,
    )  # fmt: skip
    if proc.returncode != 0:
        raise RuntimeError(f"thumbnail extraction failed: {proc.stderr.strip()}")
