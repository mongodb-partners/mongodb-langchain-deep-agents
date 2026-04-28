"""VirtualFilesystem — backend-agnostic coordinator for blob + metadata."""
from __future__ import annotations

import contextlib

from .base import (
    BlobStore,
    FileMetadata,
    VfsFileNotFoundError,
    VfsQuotaExceededError,
)
from .metadata import VfsMetadataStore


class VirtualFilesystem:
    def __init__(
        self,
        *,
        backend: BlobStore,
        metadata: VfsMetadataStore,
        max_bytes: int,
    ) -> None:
        self.backend = backend
        self.metadata = metadata
        self.max_bytes = max_bytes

    def write_file(
        self,
        thread_id: str,
        path: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> FileMetadata:
        if len(data) > self.max_bytes:
            raise VfsQuotaExceededError(
                f"file {path!r} is {len(data)} bytes; max {self.max_bytes} bytes"
            )

        # On upsert, reclaim the prior blob so we don't leak orphaned GridFS/S3 objects.
        prior = self.metadata.get(thread_id, path)
        if prior is not None:
            # Best-effort cleanup. The metadata upsert below still moves the
            # canonical locator forward.
            with contextlib.suppress(Exception):
                self.backend.delete(prior.locator)

        locator = self.backend.put(thread_id, path, data, content_type=content_type)
        return self.metadata.upsert(
            thread_id=thread_id,
            path=path,
            size=len(data),
            content_type=content_type,
            backend=self.backend.backend,
            locator=locator,
        )

    def read_file(self, thread_id: str, path: str) -> bytes:
        meta = self.metadata.get(thread_id, path)
        if meta is None:
            raise VfsFileNotFoundError(f"no such file {path!r} for thread {thread_id!r}")
        return self.backend.get(meta.locator)

    def delete_file(self, thread_id: str, path: str) -> bool:
        meta = self.metadata.delete(thread_id, path)
        if meta is None:
            return False
        # Metadata is the source of truth; leave stale blobs to housekeeping.
        with contextlib.suppress(Exception):
            self.backend.delete(meta.locator)
        return True

    def list_files(self, thread_id: str) -> list[FileMetadata]:
        return self.metadata.list_all(thread_id)

    def glob_files(self, thread_id: str, pattern: str) -> list[FileMetadata]:
        return self.metadata.glob(thread_id, pattern)
