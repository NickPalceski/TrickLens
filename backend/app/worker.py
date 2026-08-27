"""Stubbed analyzer + SQS consumer.

Same processing code either way: locally, the __main__ block long-polls SQS
in a loop; in production (from step 5) an SQS event-source-mapping invokes
lambda_handler once per message instead. Only the trigger differs — polling
vs. invoked is the worker's dev/prod seam, same idea as AWS_ENDPOINT_URL
elsewhere in the app.

The scorer here stands in for the real analyzer (step 6): it fabricates
output in the exact shape the real one will produce — six subscores, a
confidence, and occasionally `unanalyzable` with a specific reason — so
everything downstream (schemas, the publish gate, eventually the UI) gets
built and exercised against the real shape now. See docs/ARCHITECTURE.md's
build-order rationale for why step 3 stubs this instead of skipping it.
"""

import asyncio
import json
import logging
import random
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.db import SessionLocal
from app.models.clip import Analysis, Clip
from app.models.enums import ClipStatus
from app.services.queue import get_queue

log = logging.getLogger("tricklens.worker")

MODEL_VERSION = "stub-v1"

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


async def _process_message(body: dict[str, Any]) -> None:
    clip_id = uuid.UUID(body["clip_id"])

    async with SessionLocal() as db:
        clip = await db.scalar(select(Clip).where(Clip.id == clip_id))
        if clip is None:
            log.warning("worker: clip %s no longer exists, dropping message", clip_id)
            return
        if clip.status != ClipStatus.QUEUED:
            # SQS is at-least-once delivery — redelivery of a message this
            # worker already handled is an expected case, not an error.
            log.info("worker: clip %s is %s, not queued — skipping", clip_id, clip.status)
            return

        clip.status = ClipStatus.ANALYZING
        await db.commit()

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
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s | %(message)s"
    )
    asyncio.run(_poll_forever())
