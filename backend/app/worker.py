"""SQS consumer: media processing (step 6a) + stubbed scorer.

Same processing code either way: locally, the __main__ block long-polls SQS
in a loop; in production (from step 5) an SQS event-source-mapping invokes
lambda_handler once per message instead. Only the trigger differs — polling
vs. invoked is the worker's dev/prod seam, same idea as AWS_ENDPOINT_URL
elsewhere in the app.

With settings.analyzer == "real" (the worker image, Dockerfile.worker), the
raw upload is first probed, transcoded to processed/ and thumbnailed via
app/analyzer/media.py; with "stub" (the API image and its test suite, which
have no ffmpeg) that step is skipped entirely.

The scorer here stands in for the real analyzer (step 6c): it fabricates
output in the exact shape the real one will produce — six subscores, a
confidence, and occasionally `unanalyzable` with a specific reason — so
everything downstream (schemas, the publish gate, eventually the UI) gets
built and exercised against the real shape now. See docs/ARCHITECTURE.md's
build-order rationale for why step 3 stubs this instead of skipping it.
"""

import asyncio
import json
import logging
import os
import random
import tempfile
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select, update

from app.config import get_settings
from app.db import SessionLocal
from app.logs import configure_logging
from app.models.clip import Analysis, Clip
from app.models.enums import ClipStatus
from app.services.queue import get_queue
from app.services.storage import PREFIX_PROCESSED, PREFIX_THUMBS, get_storage

# At import, not in __main__, so it also applies under Lambda (see app/logs.py).
configure_logging()
log = logging.getLogger("tricklens.worker")

MODEL_VERSION = "stub-v1"

# How long an `analyzing` clip belongs to the run that claimed it. It must
# be longer than the worker Lambda's 300s timeout (infra/lambda.tf), so a
# clip still `analyzing` after this can only mean its run died. It must also
# be shorter than the SQS visibility timeout (1800s in prod, 600s locally),
# so a redelivery arrives after the lease has expired, not before.
ANALYZING_LEASE = timedelta(seconds=360)

_SUBSCORES = ("pop", "landing_stability", "roll_away", "stomp", "compactness", "catch")
_FAILURE_REASONS = (
    "skater too far from camera",
    "trick left the frame",
    "too dark",
    "no clean airtime found",
    "no landed trick detected",
)


def _stub_score(clip_id: uuid.UUID) -> dict[str, Any]:
    """Deterministic given the clip id, so re-running the same clip in dev
    reproduces the same result instead of a new random one every time."""
    rng = random.Random(clip_id.int)

    if rng.random() < 0.1:
        return {
            "confidence": round(rng.uniform(0.30, 0.55), 2),
            "failure_reason": rng.choice(_FAILURE_REASONS),
        }

    breakdown = {name: round(rng.uniform(45, 97), 1) for name in _SUBSCORES}
    return {
        "confidence": round(rng.uniform(0.82, 0.99), 2),
        "steeze_breakdown": breakdown,
        "steeze_score": round(sum(breakdown.values()) / len(breakdown), 1),
    }


async def _process_media(clip: Clip) -> str | None:
    """Probe, transcode and thumbnail the raw upload (step 6a), updating
    `clip` in place. Returns a user-facing failure reason if the file itself
    is unusable, None on success. Any other exception propagates, so SQS
    retries the message.

    Imported lazily: app.analyzer is worker-image-only code, and this module
    is also imported by the API image's test suite.
    """
    from app.analyzer import localize, media, stage_b

    storage = get_storage()
    ext = os.path.splitext(clip.s3_key)[1]
    with tempfile.TemporaryDirectory(prefix="tricklens-") as tmp:
        raw = os.path.join(tmp, f"raw{ext}")
        processed = os.path.join(tmp, "processed.mp4")
        thumb = os.path.join(tmp, "thumb.jpg")

        await storage.download(clip.s3_key, raw)
        try:
            info = await asyncio.to_thread(media.probe, raw)
            await asyncio.to_thread(media.transcode, raw, processed, info)
        except media.MediaError as e:
            return e.reason

        # Stage A (6b): find the tricks. Advisory until 6c, since scoring is
        # still the stub. So a failure here is logged and the clip carries
        # on rather than becoming unanalyzable, and the windows themselves
        # are only logged, not stored.
        thumb_at_ms = info.duration_ms // 2
        try:
            processed_info = await asyncio.to_thread(media.probe, processed)
            stage_a = await asyncio.to_thread(
                localize.analyze, processed, processed_info, get_settings().yolox_model_path
            )
        except Exception:
            log.exception("worker: clip %s stage A failed, continuing without it", clip.id)
        else:
            log.info(
                "worker: clip %s stage A: %d trick(s) %s | skater in %.0f%% of samples, "
                "%.2f of frame height | %s",
                clip.id,
                len(stage_a.windows),
                [(round(w.pop_ms), round(w.apex_ms), round(w.land_ms)) for w in stage_a.windows],
                100 * stage_a.skater_coverage,
                stage_a.skater_height_frac,
                {k: round(v, 2) for k, v in stage_a.timings_s.items()},
            )
            if stage_a.windows:
                # The poster frame is the highest moment of the biggest pop.
                best = max(stage_a.windows, key=lambda w: w.peak_elevation)
                thumb_at_ms = int(best.apex_ms)
            # Stage B (6c-1): pose + board at native fps per trick. Same
            # advisory rules as Stage A until 6c-3 starts scoring from it.
            settings = get_settings()
            for n, window in enumerate(stage_a.windows, 1):
                try:
                    obs = await asyncio.to_thread(
                        stage_b.observe,
                        processed,
                        processed_info,
                        stage_a,
                        window,
                        settings.yolox_model_path,
                        settings.pose_model_path,
                    )
                except Exception:
                    log.exception("worker: clip %s stage B trick %d failed", clip.id, n)
                    continue
                log.info(
                    "worker: clip %s stage B trick %d: takeoff %s touchdown %s | pose %.0f%%, "
                    "feet vis %.2f, board %.0f%% | %s",
                    clip.id,
                    n,
                    None if obs.takeoff_ms is None else round(obs.takeoff_ms),
                    None if obs.touchdown_ms is None else round(obs.touchdown_ms),
                    100 * obs.pose.found_frac,
                    obs.pose.feet_visibility(),
                    100 * obs.board_found_frac,
                    {k: round(v, 2) for k, v in obs.timings_s.items()},
                )
        await asyncio.to_thread(media.thumbnail, processed, thumb, thumb_at_ms)

        processed_key = f"{PREFIX_PROCESSED}/{clip.id}.mp4"
        thumb_key = f"{PREFIX_THUMBS}/{clip.id}.jpg"
        await storage.upload(processed, processed_key, "video/mp4")
        await storage.upload(thumb, thumb_key, "image/jpeg")

    clip.processed_key = processed_key
    clip.thumb_key = thumb_key
    # Server-verified now, overwriting what the browser reported in
    # POST /clips (see docs/components/analyzer.md, Media).
    clip.duration_ms = info.duration_ms
    clip.source_fps = round(info.fps)
    return None


async def _process_message(body: dict[str, Any]) -> None:
    clip_id = uuid.UUID(body["clip_id"])

    async with SessionLocal() as db:
        # Claim the clip atomically: one UPDATE, so two consumers can never
        # both own it. SQS is at-least-once, so a duplicate delivery must be
        # able to lose this race cleanly.
        #
        # A stale ANALYZING clip is claimable too. A Lambda timeout or crash
        # mid-analysis leaves the clip there, and SQS redelivers after the
        # visibility timeout. Without this, the clip would be stuck in
        # `analyzing` forever. Reprocessing is safe: every S3 key is
        # deterministic per clip and simply overwritten.
        claimed = await db.scalar(
            update(Clip)
            .where(
                Clip.id == clip_id,
                or_(
                    Clip.status == ClipStatus.QUEUED,
                    and_(
                        Clip.status == ClipStatus.ANALYZING,
                        Clip.updated_at < func.now() - ANALYZING_LEASE,
                    ),
                ),
            )
            .values(status=ClipStatus.ANALYZING, updated_at=func.now())
            .returning(Clip.id)
        )
        await db.commit()

        clip = await db.scalar(select(Clip).where(Clip.id == clip_id))
        if clip is None:
            log.warning("worker: clip %s no longer exists, dropping message", clip_id)
            return
        if claimed is None:
            # Finished work (ANALYZED onward), or another run's live lease.
            log.info("worker: clip %s is %s, not claimable — skipping", clip_id, clip.status)
            return

        if get_settings().analyzer == "real":
            failure = await _process_media(clip)
            if failure is not None:
                db.add(
                    Analysis(
                        clip_id=clip.id,
                        model_version=MODEL_VERSION,
                        confidence=Decimal("0"),
                        failure_reason=failure,
                    )
                )
                clip.status = ClipStatus.UNANALYZABLE
                await db.commit()
                log.info("worker: clip %s -> %s (%s)", clip_id, clip.status, failure)
                return

        result = _stub_score(clip.id)

        db.add(
            Analysis(
                clip_id=clip.id,
                model_version=MODEL_VERSION,
                confidence=Decimal(str(result["confidence"])),
                steeze_breakdown=result.get("steeze_breakdown"),
                failure_reason=result.get("failure_reason"),
            )
        )
        if "steeze_breakdown" in result:
            clip.status = ClipStatus.ANALYZED
            clip.steeze_score = Decimal(str(result["steeze_score"]))
        else:
            clip.status = ClipStatus.UNANALYZABLE
        await db.commit()

    log.info("worker: clip %s -> %s", clip_id, clip.status)


async def _poll_forever() -> None:
    queue = get_queue()
    log.info("worker: polling %s", queue.queue_url)
    while True:
        for message in await queue.receive_messages(wait_time_seconds=20):
            try:
                await _process_message(json.loads(message["body"]))
            except Exception:
                log.exception(
                    "worker: failed processing message %s, leaving for redrive",
                    message["message_id"],
                )
                continue
            # Delete only after processing has committed — a crash before
            # this point just means SQS redelivers, which _process_message
            # already handles idempotently via the status=QUEUED check.
            await queue.delete_message(message["receipt_handle"])


def lambda_handler(event: dict[str, Any], _context: Any) -> None:
    """Production entrypoint (from step 5): one invocation per SQS batch."""

    async def _run() -> None:
        for record in event["Records"]:
            await _process_message(json.loads(record["body"]))

    asyncio.run(_run())


if __name__ == "__main__":
    asyncio.run(_poll_forever())
