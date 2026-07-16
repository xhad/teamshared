"""S3-compatible object storage publisher for public shared-file mirroring.

Wraps a synchronous ``boto3`` S3 client in :func:`asyncio.to_thread` so the
async event loop is never blocked. Railway buckets (and R2, MinIO, AWS S3, etc.)
all speak the S3 API, so this is the only storage abstraction the file-sharing
feature needs.

When the four required settings (endpoint, bucket, access key, secret key) are
not all present, the publisher is ``None`` and file publish/update degrade
gracefully (Postgres stays canonical; the public route still renders from
Postgres). This keeps local dev and tests bucket-free.
"""

from __future__ import annotations

import asyncio
from typing import Any

from teamshared.logging import get_logger

log = get_logger(__name__)


def _client_factory(
    endpoint: str,
    access_key: str,
    secret_key: str,
    region: str | None,
) -> Any:
    """Build a boto3 S3 client. Imported lazily so the dep is optional."""
    import boto3  # type: ignore[import-untyped]
    from botocore.config import Config  # type: ignore[import-untyped]

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region or "us-east-1",
        config=Config(signature_version="s3v4"),
    )


class FilePublisher:
    """Eagerly pushes rendered shared-file HTML to an S3-compatible bucket.

    Object keys: ``{share_token}/v{version}.html`` (per-version snapshot) and
    ``{share_token}/index.html`` (always the latest version, for the CDN root).
    """

    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str | None = None,
        public_base_url: str | None = None,
        client_factory: Any = _client_factory,
    ) -> None:
        self._bucket = bucket
        self._public_base_url = public_base_url
        self._client = client_factory(endpoint, access_key, secret_key, region)

    @property
    def public_base_url(self) -> str | None:
        return self._public_base_url

    async def publish_html(
        self, share_token: str, version: int, html: str
    ) -> None:
        """PUT the versioned snapshot and the latest index.html."""
        version_key = f"{share_token}/v{version}.html"
        index_key = f"{share_token}/index.html"
        body = html.encode("utf-8")
        await asyncio.to_thread(self._put_object, version_key, body)
        await asyncio.to_thread(self._put_object, index_key, body)
        log.info(
            "file_published_to_bucket",
            share_token=share_token,
            version=version,
            bucket=self._bucket,
        )

    async def unpublish(self, share_token: str) -> None:
        """Best-effort delete of all objects under the token prefix."""
        await asyncio.to_thread(self._delete_prefix, share_token)
        log.info("file_unpublished_from_bucket", share_token=share_token)

    def _put_object(self, key: str, body: bytes) -> None:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=body,
            ContentType="text/html; charset=utf-8",
        )

    def _delete_prefix(self, prefix: str) -> None:
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=f"{prefix}/"):
            objs = page.get("Contents") or []
            if not objs:
                continue
            self._client.delete_objects(
                Bucket=self._bucket,
                Delete={"Objects": [{"Key": o["Key"]} for o in objs], "Quiet": True},
            )

    def public_url(self, share_token: str, version: int | None = None) -> str | None:
        """Direct CDN URL for a version (or the index if version is None)."""
        if not self._public_base_url:
            return None
        base = self._public_base_url.rstrip("/")
        if version is None:
            return f"{base}/{share_token}/index.html"
        return f"{base}/{share_token}/v{version}.html"


def build_file_publisher(settings: Any) -> FilePublisher | None:
    """Construct a FilePublisher from settings, or None when unconfigured.

    All four of endpoint, bucket, access key, and secret key must be present;
    otherwise the publisher is None and the file-sharing feature degrades to
    Postgres-only serving.
    """
    if not (
        settings.object_storage_endpoint
        and settings.object_storage_bucket
        and settings.object_storage_access_key
        and settings.object_storage_secret_key
    ):
        return None
    return FilePublisher(
        endpoint=settings.object_storage_endpoint,
        bucket=settings.object_storage_bucket,
        access_key=settings.object_storage_access_key,
        secret_key=settings.object_storage_secret_key,
        region=settings.object_storage_region,
        public_base_url=settings.object_storage_public_base_url,
        client_factory=_client_factory,
    )
