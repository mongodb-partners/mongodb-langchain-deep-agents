"""Sub-phase 06: GridFS backend.

GridFS insists on a real ``pymongo.database.Database`` and rejects mongomock,
so we inject a small in-memory GridFS shim that mirrors the three methods the
backend actually uses (``put``, ``get``, ``delete``) plus ``NoFile``.
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pytest

from . import vfs_contract


class _NoFile(Exception):
    """Stands in for gridfs.errors.NoFile."""


class _FakeGridFile:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class _FakeGridFS:
    """In-memory gridfs look-alike. Locators are ``str(ObjectId)`` shaped,
    but here we simply use UUIDs so tests don't depend on bson."""

    NoFile = _NoFile

    def __init__(self, db: Any) -> None:
        self._db = db
        self._store: dict[str, bytes] = {}
        self._meta: dict[str, dict[str, Any]] = {}

    def put(self, data: bytes, **kwargs: Any) -> str:
        locator = uuid.uuid4().hex
        self._store[locator] = data
        self._meta[locator] = kwargs
        return locator

    def get(self, locator: str) -> _FakeGridFile:
        if locator not in self._store:
            raise _NoFile(locator)
        return _FakeGridFile(self._store[locator])

    def delete(self, locator: str) -> None:
        self._store.pop(locator, None)
        self._meta.pop(locator, None)


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    from deep_agent import config

    config.get_settings.cache_clear()


def _make_backend() -> Any:
    import mongomock

    from deep_agent.vfs.gridfs_backend import GridFSBackend

    db = mongomock.MongoClient()["deep_agent_test"]
    return GridFSBackend(db, fs_factory=_FakeGridFS)


def test_TC_06_010_put_get_round_trip() -> None:
    backend = _make_backend()
    locator = backend.put("t1", "x.txt", b"hello", content_type="text/plain")
    assert backend.get(locator) == b"hello"


def test_TC_06_020_delete_removes_blob() -> None:
    backend = _make_backend()
    locator = backend.put("t1", "x.txt", b"hello", content_type="text/plain")
    backend.delete(locator)
    with pytest.raises(_NoFile):
        backend.get(locator)


def test_TC_06_030_backend_label() -> None:
    backend = _make_backend()
    assert backend.backend == "gridfs"


def test_TC_06_040_full_contract_via_virtualfilesystem() -> None:
    import mongomock

    from deep_agent.vfs import VfsMetadataStore, VirtualFilesystem
    from deep_agent.vfs.gridfs_backend import GridFSBackend

    db = mongomock.MongoClient()["deep_agent_test"]
    coll = db["vfs_files"]
    coll.create_index([("thread_id", 1), ("path", 1)], unique=True)
    metadata = VfsMetadataStore(coll)
    backend = GridFSBackend(db, fs_factory=_FakeGridFS)
    vfs = VirtualFilesystem(backend=backend, metadata=metadata, max_bytes=1024)

    vfs_contract.assert_round_trip(vfs)
    vfs_contract.assert_metadata_fields(vfs)
    vfs_contract.assert_upsert_cleans_old_blob(vfs, blob_store=_ExistsAdapter(backend))
    vfs_contract.assert_thread_scoping(vfs)
    vfs_contract.assert_size_limit(vfs)
    vfs_contract.assert_delete_missing(vfs)
    vfs_contract.assert_read_missing_raises(vfs)
    vfs_contract.assert_glob_scoped(vfs)


class _ExistsAdapter:
    """Adapter so the contract helper can ask whether the blob is still present."""

    def __init__(self, backend: Any) -> None:
        self._backend = backend

    def exists(self, locator: str) -> bool:
        try:
            self._backend.get(locator)
        except _NoFile:
            return False
        return True


def test_TC_06_050_get_vfs_returns_gridfs_backend_when_backend_gridfs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mongomock

    from deep_agent import vfs as vfs_pkg

    monkeypatch.setenv("VFS_BACKEND", "gridfs")
    vfs_pkg.get_vfs.cache_clear()
    db = mongomock.MongoClient()["deep_agent_test"]
    with patch("deep_agent.vfs.get_db", return_value=db), patch(
        "deep_agent.vfs.gridfs_backend.gridfs"
    ) as fake_gridfs_mod:
        fake_gridfs_mod.GridFS.side_effect = lambda database: _FakeGridFS(database)
        fake_gridfs_mod.errors = type("E", (), {"NoFile": _NoFile})
        instance = vfs_pkg.get_vfs()

    from deep_agent.vfs.gridfs_backend import GridFSBackend

    assert isinstance(instance.backend, GridFSBackend)
    assert instance.max_bytes == 50 * 1024 * 1024
    vfs_pkg.get_vfs.cache_clear()
