"""Private MinIO object-store provider."""

from __future__ import annotations

import io
import re
from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from .base import (
    ObjectInfo,
    ObjectStore,
    ObjectStoreConfigurationError,
    ObjectStoreNotFoundError,
    ObjectStoreTransportError,
)

_BUCKET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")


class MinIOObjectStore(ObjectStore):
    """MinIO-backed object storage.

    New buckets retain MinIO's private-by-default policy. This class never
    creates anonymous/public bucket policies.
    """

    def __init__(
        self,
        *,
        endpoint: str = "localhost:20000",
        access_key: str = "minioadmin",
        secret_key: str = "minioadmin",
        bucket: str = "novel-agent",
        secure: bool = False,
        region: str | None = None,
        client: Any | None = None,
    ) -> None:
        if not endpoint.strip() or "://" in endpoint:
            raise ObjectStoreConfigurationError(
                "MinIO endpoint must be host:port without a URL scheme"
            )
        if not access_key or not secret_key:
            raise ObjectStoreConfigurationError("MinIO credentials must not be empty")
        if not _BUCKET_PATTERN.fullmatch(bucket):
            raise ObjectStoreConfigurationError("Invalid MinIO bucket name")
        self.bucket = bucket
        self._client = client or self._make_client(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
            region=region,
        )

    @staticmethod
    def _make_client(
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool,
        region: str | None,
    ) -> Any:
        try:
            from minio import Minio
        except ImportError as exc:
            raise ObjectStoreConfigurationError(
                "MinIOObjectStore requires the 'minio' package"
            ) from exc
        try:
            return Minio(
                endpoint,
                access_key=access_key,
                secret_key=secret_key,
                secure=secure,
                region=region,
            )
        except Exception as exc:
            raise ObjectStoreConfigurationError(
                f"Invalid MinIO client configuration: {exc}"
            ) from exc

    def ensure_bucket(self) -> None:
        try:
            if not self._client.bucket_exists(self.bucket):
                self._client.make_bucket(self.bucket)
        except Exception as exc:
            raise ObjectStoreTransportError(
                f"Could not ensure MinIO bucket {self.bucket!r}: {exc}"
            ) from exc

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> ObjectInfo:
        key = self._validate_key(key)
        self.ensure_bucket()
        try:
            result = self._client.put_object(
                self.bucket,
                key,
                io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
        except Exception as exc:
            raise ObjectStoreTransportError(f"MinIO upload failed for {key!r}: {exc}") from exc
        return ObjectInfo(
            bucket=self.bucket,
            key=key,
            size=len(data),
            etag=getattr(result, "etag", None),
            content_type=content_type,
        )

    def put_file(
        self,
        key: str,
        path: str | Path,
        *,
        content_type: str = "application/octet-stream",
    ) -> ObjectInfo:
        key = self._validate_key(key)
        source = Path(path)
        if not source.is_file():
            raise ObjectStoreConfigurationError(f"Upload source is not a file: {source}")
        self.ensure_bucket()
        try:
            result = self._client.fput_object(
                self.bucket,
                key,
                str(source),
                content_type=content_type,
            )
        except Exception as exc:
            raise ObjectStoreTransportError(f"MinIO upload failed for {key!r}: {exc}") from exc
        return ObjectInfo(
            bucket=self.bucket,
            key=key,
            size=source.stat().st_size,
            etag=getattr(result, "etag", None),
            content_type=content_type,
        )

    def get_bytes(self, key: str) -> bytes:
        key = self._validate_key(key)
        response: Any | None = None
        try:
            response = self._client.get_object(self.bucket, key)
            return response.read()
        except Exception as exc:
            if _is_not_found(exc):
                raise ObjectStoreNotFoundError(f"Object not found: {key}") from exc
            raise ObjectStoreTransportError(f"MinIO download failed for {key!r}: {exc}") from exc
        finally:
            if response is not None:
                response.close()
                response.release_conn()

    def stat(self, key: str) -> ObjectInfo:
        key = self._validate_key(key)
        try:
            result = self._client.stat_object(self.bucket, key)
        except Exception as exc:
            if _is_not_found(exc):
                raise ObjectStoreNotFoundError(f"Object not found: {key}") from exc
            raise ObjectStoreTransportError(f"MinIO stat failed for {key!r}: {exc}") from exc
        return ObjectInfo(
            bucket=self.bucket,
            key=key,
            size=int(getattr(result, "size", 0)),
            etag=getattr(result, "etag", None),
            content_type=getattr(result, "content_type", None),
            last_modified=getattr(result, "last_modified", None),
        )

    def exists(self, key: str) -> bool:
        try:
            self.stat(key)
            return True
        except ObjectStoreNotFoundError:
            return False

    def remove(self, key: str) -> None:
        key = self._validate_key(key)
        try:
            self._client.remove_object(self.bucket, key)
        except Exception as exc:
            if _is_not_found(exc):
                return
            raise ObjectStoreTransportError(f"MinIO delete failed for {key!r}: {exc}") from exc

    def presigned_get(self, key: str, *, expires: timedelta = timedelta(minutes=15)) -> str:
        key = self._validate_key(key)
        if expires <= timedelta(0) or expires > timedelta(days=7):
            raise ObjectStoreConfigurationError(
                "Presigned URL expiry must be between 1 second and 7 days"
            )
        try:
            return str(
                self._client.presigned_get_object(
                    self.bucket,
                    key,
                    expires=expires,
                )
            )
        except Exception as exc:
            raise ObjectStoreTransportError(
                f"Could not create presigned URL for {key!r}: {exc}"
            ) from exc

    def health(self) -> bool:
        try:
            self._client.bucket_exists(self.bucket)
            return True
        except Exception:
            return False

    @staticmethod
    def _validate_key(key: str) -> str:
        if not key or "\x00" in key or "\\" in key or key.startswith("/"):
            raise ObjectStoreConfigurationError("Invalid object key")
        path = PurePosixPath(key)
        if any(part in {"", ".", ".."} for part in path.parts):
            raise ObjectStoreConfigurationError("Object key contains unsafe path segments")
        if len(key.encode("utf-8")) > 1024:
            raise ObjectStoreConfigurationError("Object key exceeds 1024 UTF-8 bytes")
        return key


def _is_not_found(exc: Exception) -> bool:
    code = getattr(exc, "code", None)
    return code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket", "NotFound"}
