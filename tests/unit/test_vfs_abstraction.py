"""Sub-phase 05: VFS abstraction against an in-memory stub backend."""
from __future__ import annotations

import pytest

from . import vfs_contract


@pytest.fixture
def vfs(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    import mongomock

    from deep_agent.vfs import VfsMetadataStore, VirtualFilesystem

    client = mongomock.MongoClient()
    # Enforce compound unique index the same way ensure_indexes() does
    coll = client["deep_agent_test"]["vfs_files"]
    coll.create_index([("thread_id", 1), ("path", 1)], unique=True)
    metadata = VfsMetadataStore(coll)
    store = vfs_contract.DictBlobStore()
    return VirtualFilesystem(backend=store, metadata=metadata, max_bytes=1024)


def test_TC_05_010_round_trip(vfs) -> None:  # type: ignore[no-untyped-def]
    vfs_contract.assert_round_trip(vfs)


def test_TC_05_020_metadata_fields(vfs) -> None:  # type: ignore[no-untyped-def]
    vfs_contract.assert_metadata_fields(vfs)


def test_TC_05_040_upsert_cleans_old_blob(vfs) -> None:  # type: ignore[no-untyped-def]
    vfs_contract.assert_upsert_cleans_old_blob(vfs, blob_store=vfs.backend)


def test_TC_05_050_thread_scoping(vfs) -> None:  # type: ignore[no-untyped-def]
    vfs_contract.assert_thread_scoping(vfs)


def test_TC_05_060_size_limit(vfs) -> None:  # type: ignore[no-untyped-def]
    vfs_contract.assert_size_limit(vfs)


def test_TC_05_070_delete_missing(vfs) -> None:  # type: ignore[no-untyped-def]
    vfs_contract.assert_delete_missing(vfs)


def test_TC_05_080_read_missing_raises(vfs) -> None:  # type: ignore[no-untyped-def]
    vfs_contract.assert_read_missing_raises(vfs)


def test_TC_05_090_glob_scoped(vfs) -> None:  # type: ignore[no-untyped-def]
    vfs_contract.assert_glob_scoped(vfs)


def test_TC_05_030_duplicate_upsert_does_not_insert_twice(vfs) -> None:  # type: ignore[no-untyped-def]
    vfs.write_file("t1", "x.txt", b"one", content_type="text/plain")
    vfs.write_file("t1", "x.txt", b"two", content_type="text/plain")
    vfs.write_file("t1", "x.txt", b"three", content_type="text/plain")
    listing = vfs.list_files("t1")
    assert len(listing) == 1
    assert listing[0].path == "x.txt"
    assert vfs.read_file("t1", "x.txt") == b"three"
