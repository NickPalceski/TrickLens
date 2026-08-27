"""SQS access.

The buffer between "user uploaded a clip" and "worker analyzed it".

This is structural, not an optimization: analysis takes 30-90 seconds and API
Gateway hard-caps a request at 29. Doing the work inline is not slow, it is
impossible. The queue also buys retries, a dead-letter queue for poison
clips, and backpressure when uploads spike.
"""

import asyncio
import json
from functools import lru_cache
from typing import Any

import boto3
from botocore.config import Config

from app.config import get_settings


@lru_cache
def _client():
    settings = get_settings()
    return boto3.client(
        "sqs",
        endpoint_url=settings.boto_endpoint,
        region_name=settings.aws_region,
        config=Config(retries={"max_attempts": 3, "mode": "standard"}),
    )


class AnalysisQueue:
    def __init__(self) -> None:
        self.queue_url = get_settings().sqs_analysis_queue_url

    async def enqueue(self, payload: dict[str, Any]) -> str:
        """Put a clip on the queue. Returns the SQS message id."""
        resp = await asyncio.to_thread(
            _client().send_message,
            QueueUrl=self.queue_url,
            MessageBody=json.dumps(payload),
        )
        return resp["MessageId"]

    async def depth(self) -> dict[str, int]:
        """Approximate queue depth — useful for health checks and debugging."""
        resp = await asyncio.to_thread(
            _client().get_queue_attributes,
            QueueUrl=self.queue_url,
            AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
        )
        attrs = resp.get("Attributes", {})
        return {
            "waiting": int(attrs.get("ApproximateNumberOfMessages", 0)),
            "in_flight": int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0)),
        }

    async def receive_messages(
        self, max_messages: int = 1, wait_time_seconds: int = 20
    ) -> list[dict[str, str]]:
        """Long-poll for messages. Returns [] on a normal empty-queue timeout.

        wait_time_seconds > 0 makes this a long poll: SQS holds the request
        open instead of returning immediately, which is both cheaper (far
        fewer empty responses) and lower-latency than short-polling in a loop.
        """
        resp = await asyncio.to_thread(
            _client().receive_message,
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=wait_time_seconds,
        )
        return [
            {"message_id": m["MessageId"], "receipt_handle": m["ReceiptHandle"], "body": m["Body"]}
            for m in resp.get("Messages", [])
        ]

    async def delete_message(self, receipt_handle: str) -> None:
        """Remove a message after it's been fully processed and committed —
        not before, or a crash mid-processing loses the message for good
        instead of just triggering a harmless redelivery."""
        await asyncio.to_thread(
            _client().delete_message, QueueUrl=self.queue_url, ReceiptHandle=receipt_handle
        )

    async def check(self) -> None:
        """Health probe. Raises if the queue is unreachable."""
        await self.depth()


def get_queue() -> AnalysisQueue:
    return AnalysisQueue()
