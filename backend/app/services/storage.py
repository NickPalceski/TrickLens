"""S3 access.

One of exactly two modules that know AWS exists (the other is queue.py).
Everything else in the app goes through this interface, which is what makes
"LocalStack locally, real S3 in production" a config change rather than a
code change.
"""

import asyncio
from functools import lru_cache

import boto3
from botocore.config import Config

from app.config import get_settings

# S3 key prefixes. Kept here so the layout is defined in one place — the
# lifecycle rule that expires abandoned drafts keys off "raw/".
PREFIX_RAW = "raw"  # exactly what the user uploaded
PREFIX_PROCESSED = "processed"  # worker's 720p transcode
PREFIX_THUMBS = "thumbs"  # poster frames
PREFIX_AVATARS = "avatars"


@lru_cache
def _client():
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.boto_endpoint,  # None in production -> real AWS
        region_name=settings.aws_region,
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


class Storage:
    def __init__(self) -> None:
        settings = get_settings()
        self.bucket = settings.s3_bucket
        self.cdn_base = settings.cdn_base_url.rstrip("/")
        self._internal_endpoint = settings.boto_endpoint
        self._public_endpoint = settings.aws_public_endpoint_url.rstrip("/") or None

    def public_url(self, key: str) -> str:
        """Build a delivery URL from a stored key.

        The database stores keys, never URLs, so swapping the bucket for a
        CloudFront domain later is a single env var.
        """
        return f"{self.cdn_base}/{key}"

    def _externalize(self, url: str) -> str:
        """Swap LocalStack's Docker-network host for one reachable from
        outside the compose network. A no-op in production, where
        boto_endpoint is already the real (externally reachable) S3
        endpoint and aws_public_endpoint_url is unset — see config.py.
        """
        if self._public_endpoint and self._internal_endpoint:
            return url.replace(self._internal_endpoint, self._public_endpoint, 1)
        return url

    async def presign_upload(
        self, key: str, content_type: str, expires_in: int = 900
    ) -> dict[str, str]:
        """Issue a short-lived URL the browser can PUT directly to.

        The video never passes through the API — a 30s clip would blow
        Lambda's payload limit and burn compute for no reason. The API just
        hands out a time-limited permission slip.
        """
        url = await asyncio.to_thread(
            _client().generate_presigned_url,
            ClientMethod="put_object",
            Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=expires_in,
        )
        return {"url": self._externalize(url), "key": key}

    async def presign_download(self, key: str, expires_in: int = 3600) -> str:
        url = await asyncio.to_thread(
            _client().generate_presigned_url,
            ClientMethod="get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )
        return self._externalize(url)

    async def head(self, key: str) -> dict | None:
        """Object metadata, or None if it does not exist.

        Used to confirm an upload actually landed before queueing analysis —
        a client can always claim it finished when it did not.
        """

        def _head():
            try:
                return _client().head_object(Bucket=self.bucket, Key=key)
            except _client().exceptions.ClientError:
                return None

        return await asyncio.to_thread(_head)

    async def check(self) -> None:
        """Health probe. Raises if the bucket is unreachable."""
        await asyncio.to_thread(_client().head_bucket, Bucket=self.bucket)


def get_storage() -> Storage:
    return Storage()
