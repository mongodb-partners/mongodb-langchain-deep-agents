"""Virtual filesystem: pluggable blob backend + MongoDB-backed metadata."""
from __future__ import annotations

from functools import lru_cache

import boto3

from ..config import get_settings
from ..persistence.mongo import get_db
from .base import (
    BlobStore,
    FileMetadata,
    VfsError,
    VfsFileNotFoundError,
    VfsQuotaExceededError,
)
from .filesystem import VirtualFilesystem
from .gridfs_backend import GridFSBackend
from .metadata import VfsMetadataStore
from .s3_backend import S3Backend

__all__ = [
    "BlobStore",
    "FileMetadata",
    "GridFSBackend",
    "S3Backend",
    "VfsError",
    "VfsFileNotFoundError",
    "VfsMetadataStore",
    "VfsQuotaExceededError",
    "VirtualFilesystem",
    "get_vfs",
]


@lru_cache(maxsize=16)
def get_vfs(db_name: str | None = None) -> VirtualFilesystem:
    """Return the configured :class:`VirtualFilesystem` bound to ``db_name``.

    ``db_name=None`` resolves to ``Settings.mongodb_db`` (single-domain CLI /
    worker path). The multi-domain web server passes a per-request db_name
    (e.g. ``deep_agents_<pack>``) so files + GridFS chunks land in the
    pack-specific database alongside the pack's other persistence
    (checkpointer, chat_history, plans, semantic_cache).

    Selects the blob backend from ``VFS_BACKEND``; GridFS buckets are created
    inside the resolved per-domain DB, so no data crosses packs.
    """
    s = get_settings()
    db = get_db(db_name)
    backend: BlobStore
    if s.vfs_backend == "gridfs":
        backend = GridFSBackend(db)
    elif s.vfs_backend == "s3":
        if not s.vfs_s3_bucket:  # pragma: no cover — pydantic validator blocks this
            raise ValueError("VFS_BACKEND=s3 requires VFS_S3_BUCKET")
        client = boto3.client("s3", region_name=s.vfs_s3_region)
        backend = S3Backend(
            bucket=s.vfs_s3_bucket, prefix=s.vfs_s3_prefix, client=client
        )
    else:  # pragma: no cover — pydantic already constrains the literal
        raise ValueError(f"unsupported VFS_BACKEND={s.vfs_backend}")
    metadata = VfsMetadataStore(db[s.vfs_files_collection])
    return VirtualFilesystem(backend=backend, metadata=metadata, max_bytes=s.vfs_max_bytes)
