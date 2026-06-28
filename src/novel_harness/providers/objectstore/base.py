"""Provider-neutral object-store contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from novel_harness.exceptions import ProviderError


class ObjectStoreError(ProviderError):
    """Base object-store error."""


class ObjectStoreConfigurationError(ObjectStoreError):
    """Object-store configuration or key is invalid."""


class ObjectStoreNotFoundError(ObjectStoreError):
    """The requested object does not exist."""


class ObjectStoreTransportError(ObjectStoreError):
    """The object-storage service failed."""


@dataclass(frozen=True, slots=True)
class ObjectInfo:
    """Normalized object metadata."""

    bucket: str
    key: str
    size: int
    etag: str | None = None
    content_type: str | None = None
    last_modified: datetime | None = None


class ObjectStore(ABC):
    """Synchronous private object-store interface."""

    @abstractmethod
    def ensure_bucket(self) -> None:
        """Create the private bucket if absent."""

    @abstractmethod
    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> ObjectInfo:
        """Upload bytes."""

    @abstractmethod
    def put_file(
        self,
        key: str,
        path: str | Path,
        *,
        content_type: str = "application/octet-stream",
    ) -> ObjectInfo:
        """Upload a local file."""

    @abstractmethod
    def get_bytes(self, key: str) -> bytes:
        """Download an object's bytes."""

    @abstractmethod
    def stat(self, key: str) -> ObjectInfo:
        """Return object metadata or raise ``ObjectStoreNotFoundError``."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Return whether an object exists."""

    @abstractmethod
    def remove(self, key: str) -> None:
        """Delete one object. Missing objects are treated as already deleted."""

    @abstractmethod
    def presigned_get(self, key: str, *, expires: timedelta = timedelta(minutes=15)) -> str:
        """Return a temporary read URL."""

    @abstractmethod
    def health(self) -> bool:
        """Return whether the backing service is reachable."""
