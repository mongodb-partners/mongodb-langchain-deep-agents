"""Metadata operations on the ``vfs_files`` collection.

Every operation is scoped by ``thread_id`` — enforces INV-003 (no cross-thread
visibility at the metadata layer).
"""
from __future__ import annotations

import fnmatch
from datetime import UTC, datetime
from typing import Any

from .base import FileMetadata


class VfsMetadataStore:
    def __init__(self, collection: Any) -> None:
        self._coll = collection

    @staticmethod
    def _to_metadata(doc: dict[str, Any]) -> FileMetadata:
        return FileMetadata(
            thread_id=doc["thread_id"],
            path=doc["path"],
            size=int(doc["size"]),
            content_type=doc.get("content_type", "application/octet-stream"),
            backend=doc["backend"],
            locator=doc["locator"],
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )

    def get(self, thread_id: str, path: str) -> FileMetadata | None:
        doc = self._coll.find_one({"thread_id": thread_id, "path": path})
        return None if doc is None else self._to_metadata(doc)

    def upsert(
        self,
        *,
        thread_id: str,
        path: str,
        size: int,
        content_type: str,
        backend: str,
        locator: str,
    ) -> FileMetadata:
        now = datetime.now(UTC)
        existing = self._coll.find_one({"thread_id": thread_id, "path": path})
        created_at = existing["created_at"] if existing else now
        doc = {
            "thread_id": thread_id,
            "path": path,
            "size": size,
            "content_type": content_type,
            "backend": backend,
            "locator": locator,
            "created_at": created_at,
            "updated_at": now,
        }
        self._coll.update_one(
            {"thread_id": thread_id, "path": path},
            {"$set": doc},
            upsert=True,
        )
        return self._to_metadata(doc)

    def delete(self, thread_id: str, path: str) -> FileMetadata | None:
        doc = self._coll.find_one_and_delete({"thread_id": thread_id, "path": path})
        return None if doc is None else self._to_metadata(doc)

    def list_all(self, thread_id: str) -> list[FileMetadata]:
        cursor = self._coll.find({"thread_id": thread_id}).sort("path", 1)
        return [self._to_metadata(d) for d in cursor]

    def glob(self, thread_id: str, pattern: str) -> list[FileMetadata]:
        return [m for m in self.list_all(thread_id) if fnmatch.fnmatchcase(m.path, pattern)]
