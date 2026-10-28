"""SQS consumer: media processing (step 6a) + the steeze analyzer (6c).

Same processing code either way: locally, the __main__ block long-polls SQS
in a loop; in production (from step 5) an SQS event-source-mapping invokes
lambda_handler once per message instead. Only the trigger differs — polling
vs. invoked is the worker's dev/prod seam, same idea as AWS_ENDPOINT_URL
elsewhere in the app.

With settings.analyzer == "real" (the worker image, Dockerfile.worker), the
raw upload is probed, transcoded to processed/ and thumbnailed via
app/analyzer/media.py, then app/analyzer/pipeline.py finds, judges and
scores the tricks (6c-3). The gate decides the status, calibration.py the
score.

With "stub" (the API image and its test suite, which have no ffmpeg or CV
stack) all of that is skipped and _stub_score fabricates output in the
exact shape the real analyzer produces (six subscores, some n/a,
`details.tricks`, occasionally `unanalyzable` with a specific reason), so
the API keeps being built and tested against the real shape.
"""

import asyncio
import json
import logging
import os
import random
import tempfile
import time
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select, update

from app.analyzer import calibration
from app.analyzer.reasons import ANALYSIS_FAILED
from app.config import get_settings
from app.db import SessionLocal, run_in_fresh_loop
from app.logs import configure_logging
from app.models.clip import Analysis, Clip
from app.models.enums import ClipStatus
from app.services.queue import get_queue
from app.services.storage import PREFIX_PROCESSED, PREFIX_THUMBS, get_storage

# At import, not in __main__, so it also applies under Lambda (see app/logs.py).
configure_logging()
log = logging.getLogger("tricklens.worker")

STUB_MODEL_VERSION = "stub-v1"

# How long an `analyzing` clip belongs to the run that claimed it. It must
# be longer than the worker Lambda's 300s timeout (infra/lambda.tf), so a
# clip still `analyzing` after this can only mean its run died. It must also
# be shorter than the SQS visibility timeout (1800s in prod, 600s locally),
# so a redelivery arrives after the lease has expired, not before.
ANALYZING_LEASE = timedelta(seconds=360)

# The queue's maxReceiveCount (infra/sqs.tf, scripts/localstack-init.sh).
# On the delivery that number lands on, a clip whose earlier runs all died
# is given up on rather than run once more. See _give_up_on_final_receive.
MAX_RECEIVES = 3

_SUBSCORES = calibration.SUBSCORES
_FAILURE_REASONS = (
    "skater too far from camera",
    "trick left the frame",
    "too dark",
    "no clean airtime found",
    "no landed trick detected",
)


def model_version() -> str:
    """What scores this worker's clips: the stub, or the real analyzer."""
    return calibration.MODEL_VERSION if get_settings().analyzer == "real" else STUB_MODEL_VERSION


def _stub_score(clip_id: uuid.UUID) -> dict[str, Any]:
    """Deterministic given the clip id, so re-running the same clip in dev
    reproduces the same result instead of a new random one every time.
    Same keys as _analyze_real's result."""
    rng = random.Random(clip_id.int)

    if rng.random() < 0.1:
        return {
            "confidence": round(rng.uniform(0.30, 0.55), 2),
            "failure_reason": rng.choice(_FAILURE_REASONS),
        }

    # Catch is n/a about a third of the time, as it is for an ollie.
    subs: dict[str, float | None] = {name: round(rng.uniform(45, 97), 1) for name in _SUBSCORES}
    if rng.random() < 0.3:
        subs["catch"] = None
    breakdown, steeze = calibration.aggregate([subs])
    confidence = round(rng.uniform(0.82, 0.99), 2)
    pop = rng.randrange(500, 2000)
    trick = {
        "pop_ms": pop, "apex_ms": pop + 200, "land_ms": pop + 400,
        "takeoff_ms": pop + 10, "touchdown_ms": pop + 420,
        "outcome": "landed", "confidence": confidence,
        "landing": None, "measurements": None, "subscores": subs,
    }  # fmt: skip
    return {
        "confidence": confidence,
        "steeze_breakdown": breakdown,
        "steeze_score": steeze,
        "details": {"schema": 1, "stub": True, "tricks": [trick]},
    }


async def _analyze_real(clip: Clip) -> dict[str, Any]:
    """Probe, transcode, analyze and thumbnail the raw upload, updating
    `clip`'s media fields in place. Returns the result in _stub_score's
    shape, or `{"skipped": True}` for a clip posted without analysis
    (`clip.analyze` false, F4): transcoded and thumbnailed, not scored.

    A bad *file* returns its media reason, and nothing is uploaded. An
    exception from the analyzer itself (pipeline.analyze has no S3 or
    database access, so it's never an infrastructure error) is logged and
    becomes "analysis failed": a code bug would fail the same way on every
    retry. The processed clip and thumbnail are still uploaded then, so the
    owner can watch it. S3 errors propagate, so SQS retries the message.

    Imported lazily: app.analyzer's CV modules are worker-image-only, and
    this module is also imported by the API image's test suite.
    """
    from app.analyzer import media, pipeline

    settings = get_settings()
    storage = get_storage()
    ext = os.path.splitext(clip.s3_key)[1]
    with tempfile.TemporaryDirectory(prefix="tricklens-") as tmp:
        raw = os.path.join(tmp, f"raw{ext}")
        processed = os.path.join(tmp, "processed.mp4")
        thumb = os.path.join(tmp, "thumb.jpg")

        timings: dict[str, float] = {}
        t0 = time.perf_counter()
        await storage.download(clip.s3_key, raw)
        timings["download"] = time.perf_counter() - t0
        try:
            t0 = time.perf_counter()
            info = await asyncio.to_thread(media.probe, raw)
            await asyncio.to_thread(media.transcode, raw, processed, info)
            timings["probe_transcode"] = time.perf_counter() - t0
        except media.MediaError as e:
            return {"confidence": 0.0, "failure_reason": e.reason}
        log.info(
            "worker: clip %s media: %dms at %.0ffps | %s",
            clip.id,
            info.duration_ms,
            info.fps,
            {k: round(v, 2) for k, v in timings.items()},
        )

        thumb_at_ms = info.duration_ms // 2
        if not clip.analyze:
            result: dict[str, Any] = {"skipped": True}
        else:
            try:
                res = await asyncio.to_thread(
                    pipeline.analyze,
                    processed,
                    settings.yolox_model_path,
                    settings.pose_model_path,
                    f"clip {clip.id}",
                )
            except Exception:
                log.exception("worker: clip %s analysis crashed", clip.id)
                result = {"confidence": 0.0, "failure_reason": ANALYSIS_FAILED}
            else:
                _log_analysis(clip.id, res)
                thumb_at_ms = res.thumb_at_ms
                result = {
                    "confidence": round(res.confidence, 2),
                    "failure_reason": res.failure_reason,
                    "steeze_breakdown": res.breakdown,
                    "steeze_score": res.steeze_score,
                    "details": res.details(),
                }
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
    return result


def _log_analysis(clip_id: uuid.UUID, res: Any) -> None:
    """One line per stage, per trick, then the outcome. `res` is a
    pipeline.AnalysisResult (typed loosely: app.analyzer's CV modules are
    worker-image-only)."""
    a = res.stage_a
    log.info(
        "worker: clip %s stage A: %d trick(s) %s | skater in %.0f%% of samples, "
        "%.2f of frame height | %s",
        clip_id,
        len(a.windows),
        [(round(w.pop_ms), round(w.apex_ms), round(w.land_ms)) for w in a.windows],
        100 * a.skater_coverage,
        a.skater_height_frac,
        {k: round(v, 2) for k, v in a.timings_s.items()},
    )
    for n, (obs, t) in enumerate(zip(res.observations, res.verdict.tricks, strict=True), 1):
        if obs is not None:
            log.info(
                "worker: clip %s stage B trick %d: takeoff %s touchdown %s | pose %.0f%%, "
                "feet vis %.2f, board %.0f%% | %s",
                clip_id,
                n,
                None if obs.takeoff_ms is None else round(obs.takeoff_ms),
                None if obs.touchdown_ms is None else round(obs.touchdown_ms),
                100 * obs.pose.found_frac,
                obs.pose.feet_visibility(),
                100 * obs.board_found_frac,
                {k: round(v, 2) for k, v in obs.timings_s.items()},
            )
        c = t.landing
        detail = (
            ""
            if c is None
            else f" | on board {c.on_board}/{c.judged} judged of {c.sampled} sampled, "
            f"{c.implausible_boards} implausible board(s), stance "
            f"{'n/a' if c.stance is None else f'{c.stance:.2f}'}, board offset range "
            f"{'n/a' if c.board_offset_range is None else f'{c.board_offset_range:.2f}'}"
        )
        log.info(
            "worker: clip %s landing trick %d: %s, confidence %.2f%s",
            clip_id,
            n,
            t.outcome,
            t.confidence,
            detail,
        )
        if res.subscores[n - 1] is not None:
            log.info("worker: clip %s scores trick %d: %s", clip_id, n, res.subscores[n - 1])
    if res.failure_reason is None:
        log.info(
            "worker: clip %s gate: scored %d landed trick(s), steeze %s, confidence %.2f | %s",
            clip_id,
            len(res.verdict.landed),
            res.steeze_score,
            res.confidence,
            {k: round(v, 2) for k, v in res.timings_s.items()},
        )
    else:
        log.info(
            "worker: clip %s gate: failed: %s (confidence %.2f)",
            clip_id,
            res.failure_reason,
            res.confidence,
        )


async def _give_up_on_final_receive(db, clip_id: uuid.UUID) -> bool:
    """On the last SQS delivery, mark a clip whose earlier runs died
    `unanalyzable` ("analysis failed") instead of running it a third time.

    A run that dies mid-analysis leaves the clip `analyzing` with no
    analysis row. That's a Lambda timeout, an uncaught exception, or a native
    abort that no `except` can catch (MediaPipe 1.0's tcmalloc in 6c-1).
    Retrying a crash usually crashes again, and if the last receive crashed
    too, the message would land in the DLQ with the clip stuck at
    `analyzing` for good. So the last receive doesn't retry at all.

    Only a stale `analyzing` clip qualifies: one still `queued` on its last
    receive has never been tried (earlier deliveries failed before claiming
    it, e.g. the database was down), so it's processed normally. Same atomic
    UPDATE pattern as the claim below. Returns True if it gave up.
    """
    gave_up = await db.scalar(
        update(Clip)
        .where(
            Clip.id == clip_id,
            Clip.status == ClipStatus.ANALYZING,
            Clip.updated_at < func.now() - ANALYZING_LEASE,
        )
        .values(status=ClipStatus.UNANALYZABLE, updated_at=func.now())
        .returning(Clip.id)
    )
    if gave_up is None:
        return False
    db.add(
        Analysis(
            clip_id=clip_id,
            model_version=model_version(),
            confidence=Decimal("0"),
            failure_reason=ANALYSIS_FAILED,
        )
    )
    await db.commit()
    log.warning(
        "worker: clip %s -> unanalyzable (%s): earlier runs died, last receive (%d) not retried",
        clip_id,
        ANALYSIS_FAILED,
        MAX_RECEIVES,
    )
    return True


async def _process_message(body: dict[str, Any], receive_count: int = 1) -> None:
    """Process one queue message. `receive_count` is SQS's
    ApproximateReceiveCount for this delivery (1 on the first)."""
    clip_id = uuid.UUID(body["clip_id"])

    async with SessionLocal() as db:
        if receive_count >= MAX_RECEIVES and await _give_up_on_final_receive(db, clip_id):
            return

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
            result = await _analyze_real(clip)
        elif clip.analyze:
            result = _stub_score(clip.id)
        else:
            result = {"skipped": True}

        if result.get("skipped"):
            # Posted without analysis: ready to tag and publish, with no
            # score and no analysis row (docs/components/analyzer.md, Worker).
            clip.status = ClipStatus.ANALYZED
            await db.commit()
            log.info("worker: clip %s -> %s (not analyzed, by request)", clip_id, clip.status)
            return

        db.add(
            Analysis(
                clip_id=clip.id,
                model_version=model_version(),
                confidence=Decimal(str(result["confidence"])),
                steeze_breakdown=result.get("steeze_breakdown"),
                failure_reason=result.get("failure_reason"),
                details=result.get("details"),
            )
        )
        if result.get("steeze_score") is not None:
            clip.status = ClipStatus.ANALYZED
            clip.steeze_score = Decimal(str(result["steeze_score"]))
        else:
            clip.status = ClipStatus.UNANALYZABLE
        await db.commit()
        reason = result.get("failure_reason")

    log.info("worker: clip %s -> %s%s", clip_id, clip.status, f" ({reason})" if reason else "")


async def _poll_forever() -> None:
    queue = get_queue()
    log.info("worker: polling %s", queue.queue_url)
    while True:
        for message in await queue.receive_messages(wait_time_seconds=20):
            try:
                await _process_message(json.loads(message["body"]), message["receive_count"])
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
            await _process_message(
                json.loads(record["body"]), int(record["attributes"]["ApproximateReceiveCount"])
            )

    run_in_fresh_loop(_run)


if __name__ == "__main__":
    asyncio.run(_poll_forever())
