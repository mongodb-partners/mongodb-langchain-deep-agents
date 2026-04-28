"""GridFS-backed :class:`BlobStore` implementation.

GridFS requires a real ``pymongo.database.Database``. In production use, the
constructor takes the live DB handle directly. The ``fs_factory`` argument is
an injection seam so tests can pass an in-memory shim (mongomock's Database
is not accepted by :class:`gridfs.GridFS`).
"""
from __future__ import annotations

import contextlib
from typing import Any, Literal

import gridfs


class GridFSBackend:
    backend: Literal["gridfs"] = "gridfs"

    def __init__(
        self,
        db: Any,
        *,
        fs_factory: Any = None,
    ) -> None:
        factory = fs_factory if fs_factory is not None else gridfs.GridFS
        self._fs = factory(db)

    def put(
        self,
        thread_id: str,
        path: str,
        data: bytes,
        *,
        content_type: str,
    ) -> str:
        oid = self._fs.put(
            data,
            filename=path,
            content_type=content_type,
            metadata={"thread_id": thread_id, "path": path},
        )
        return str(oid)

    def get(self, locator: str) -> bytes:
        from bson import ObjectId

        try:
            oid: Any = ObjectId(locator)
        except Exception:
            # Tests inject string locators (e.g. UUID hex); pass them through.
            oid = locator
        data: bytes = self._fs.get(oid).read()
        return data

    def delete(self, locator: str) -> None:
        from bson import ObjectId

        try:
            oid: Any = ObjectId(locator)
        except Exception:
            oid = locator
        with contextlib.suppress(gridfs.errors.NoFile):
            self._fs.delete(oid)
