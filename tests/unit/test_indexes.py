"""Sub-phase 03: ensure_indexes idempotent DDL."""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from pymongo.errors import OperationFailure


class _FakeColl:
    """Mock collection recording search-index and classic-index calls."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.search_indexes: list[dict[str, Any]] = []
        self.classic_indexes: list[tuple[list[tuple[str, int]], dict[str, Any]]] = []
        self.dropped_search_indexes: list[str] = []
        # Optional scripted failures per collection
        self.search_fail_on: str | None = None
        self.search_fail_code: int | None = None
        # Optional pre-existing indexes (simulates an Atlas cluster with stale shapes)
        self.preexisting_search: list[dict[str, Any]] = []

    def create_search_index(self, model: dict[str, Any]) -> str:
        if self.search_fail_on == model["name"]:
            raise OperationFailure(
                "index already exists", code=self.search_fail_code or 68
            )
        self.search_indexes.append(model)
        # Creating also removes it from preexisting so drift-detection
        # returns False on the second call.
        self.preexisting_search = [
            ix for ix in self.preexisting_search if ix.get("name") != model["name"]
        ]
        return model["name"]

    def list_search_indexes(self, name: str | None = None) -> list[dict[str, Any]]:
        if name is None:
            return list(self.preexisting_search)
        return [ix for ix in self.preexisting_search if ix.get("name") == name]

    def drop_search_index(self, name: str) -> None:
        self.dropped_search_indexes.append(name)
        self.preexisting_search = [
            ix for ix in self.preexisting_search if ix.get("name") != name
        ]

    def create_index(self, keys: list[tuple[str, int]], **kwargs: Any) -> str:
        self.classic_indexes.append((keys, kwargs))
        return kwargs.get("name", "idx")


class _FakeDB:
    """Mock database that lazily vends ``_FakeColl`` instances and tracks
    which collections have been "created"."""

    def __init__(self, preexisting: list[str] | None = None) -> None:
        self._colls: dict[str, _FakeColl] = {}
        self._existing: set[str] = set(preexisting or [])
        self.created: list[str] = []

    def __getitem__(self, name: str) -> _FakeColl:
        return self._colls.setdefault(name, _FakeColl(name))

    def list_collection_names(self) -> list[str]:
        return sorted(self._existing)

    def create_collection(self, name: str) -> _FakeColl:
        if name in self._existing:
            raise OperationFailure("NamespaceExists", code=48)
        self._existing.add(name)
        self.created.append(name)
        return self[name]


@pytest.fixture(autouse=True)
def _clear_settings() -> None:
    from deep_agent import config

    config.get_settings.cache_clear()


def _run_ensure(db: _FakeDB) -> None:
    with patch("deep_agent.persistence.indexes.get_db", return_value=db):
        from deep_agent.persistence.indexes import ensure_indexes

        ensure_indexes()


def test_TC_03_030_kb_vector_and_search_indexes_created() -> None:
    db = _FakeDB()
    _run_ensure(db)
    kb = db["knowledge_base"]
    names = [m["name"] for m in kb.search_indexes]
    assert "vector_index" in names
    assert "search_index" in names
    # Vector index declares metadata.source filter
    vector_model = next(m for m in kb.search_indexes if m["name"] == "vector_index")
    fields = vector_model["definition"]["fields"]
    assert any(f.get("path") == "metadata.source" and f.get("type") == "filter" for f in fields)


def test_TC_03_040_cache_vector_index_created_with_llm_string_filter() -> None:
    db = _FakeDB()
    _run_ensure(db)
    cache = db["llm_cache"]
    assert len(cache.search_indexes) == 1
    model = cache.search_indexes[0]
    assert model["name"] == "llm_cache_semantic_index"
    fields = model["definition"]["fields"]
    assert any(f.get("path") == "llm_string" and f.get("type") == "filter" for f in fields)


def test_TC_03_050_memory_vector_index_created() -> None:
    db = _FakeDB()
    _run_ensure(db)
    mem = db["long_term_memory"]
    names = [m["name"] for m in mem.search_indexes]
    assert names == ["memory_semantic_index"]
    model = mem.search_indexes[0]
    fields = model["definition"]["fields"]
    # MongoDBStore.search filters by namespace_prefix; the index MUST
    # declare it as a filter or every search() fails with a
    # "Path 'namespace_prefix' needs to be indexed as filter" error.
    assert any(
        f.get("path") == "namespace_prefix" and f.get("type") == "filter"
        for f in fields
    ), "memory_semantic_index missing namespace_prefix filter"


def test_TC_03_055_chat_history_index_owned_by_langchain() -> None:
    """``ensure_indexes`` must NOT create a ``(SessionId, 1)`` index —
    ``MongoDBChatMessageHistory(create_index=True)`` owns that index under its
    own name. Creating it here under a different name raises
    ``IndexOptionsConflict`` (code 85) on first chat-history write."""
    db = _FakeDB()
    _run_ensure(db)
    hist = db["chat_history"]
    keys = [k for k, _ in hist.classic_indexes]
    assert [("SessionId", 1)] not in keys


def test_TC_03_056_stream_events_ttl_index() -> None:
    db = _FakeDB()
    _run_ensure(db)
    ev = db["stream_events"]
    found = [(keys, kw) for keys, kw in ev.classic_indexes if keys == [("ts", 1)]]
    assert found, "stream_events ts index missing"
    _, kw = found[0]
    assert kw.get("expireAfterSeconds") == 60 * 60 * 24 * 30


def test_TC_03_057_knowledge_graph_collection_and_type_index() -> None:
    """ensure_indexes provisions the knowledge_graph collection upfront and
    adds a type-filter index so traversal queries don't scan the whole graph."""
    db = _FakeDB()
    _run_ensure(db)
    assert "knowledge_graph" in db.created, "knowledge_graph collection not provisioned"
    kg = db["knowledge_graph"]
    keys = [k for k, _ in kg.classic_indexes]
    assert [("type", 1)] in keys, "knowledge_graph type index missing"


def test_TC_03_058_feedback_thread_ts_index() -> None:
    db = _FakeDB()
    _run_ensure(db)
    fb = db["feedback"]
    keys = [k for k, _ in fb.classic_indexes]
    assert [("thread_id", 1), ("ts", -1)] in keys, "feedback thread+ts index missing"


def test_TC_03_060_vfs_files_unique_compound_index() -> None:
    db = _FakeDB()
    _run_ensure(db)
    vfs = db["vfs_files"]
    found = [
        (keys, kw)
        for keys, kw in vfs.classic_indexes
        if keys == [("thread_id", 1), ("path", 1)]
    ]
    assert found, "vfs_files compound index missing"
    _, kw = found[0]
    assert kw.get("unique") is True


def test_TC_03_070_plans_unique_compound_index() -> None:
    db = _FakeDB()
    _run_ensure(db)
    plans = db["plans"]
    found = [
        (keys, kw)
        for keys, kw in plans.classic_indexes
        if keys == [("user_id", 1), ("thread_id", 1)]
    ]
    assert found, "plans compound index missing"
    _, kw = found[0]
    assert kw.get("unique") is True


def test_TC_03_082_heals_search_index_missing_filter() -> None:
    """If an existing vector index lacks a required filter path (e.g. the
    old memory index without namespace_prefix), ensure_indexes drops and
    recreates it so MongoDBStore.search stops failing."""
    db = _FakeDB()
    # Simulate a cluster with the OLD memory_semantic_index (no filter field)
    mem = db["long_term_memory"]
    mem.preexisting_search = [
        {
            "name": "memory_semantic_index",
            "latestDefinition": {
                "fields": [
                    {
                        "type": "vector",
                        "path": "embedding",
                        "numDimensions": 1024,
                        "similarity": "cosine",
                    }
                    # missing namespace_prefix filter
                ]
            },
        }
    ]
    _run_ensure(db)
    assert "memory_semantic_index" in mem.dropped_search_indexes, (
        "stale memory_semantic_index was not dropped before recreation"
    )
    # And the re-created index should carry the filter
    model = next(
        m for m in mem.search_indexes if m["name"] == "memory_semantic_index"
    )
    assert any(
        f.get("path") == "namespace_prefix" and f.get("type") == "filter"
        for f in model["definition"]["fields"]
    )


def test_TC_03_083_does_not_drop_when_filters_already_present() -> None:
    """If an existing index already has the required filter, ensure_indexes
    leaves it alone - no drop, no recreate."""
    db = _FakeDB()
    mem = db["long_term_memory"]
    mem.preexisting_search = [
        {
            "name": "memory_semantic_index",
            "latestDefinition": {
                "fields": [
                    {
                        "type": "vector",
                        "path": "embedding",
                        "numDimensions": 1024,
                        "similarity": "cosine",
                    },
                    {"type": "filter", "path": "namespace_prefix"},
                ]
            },
        }
    ]
    _run_ensure(db)
    assert "memory_semantic_index" not in mem.dropped_search_indexes


def test_TC_03_080_idempotent_on_duplicate_index() -> None:
    db = _FakeDB()
    # Pre-populate and script the vector-index call to "already exists"
    kb = db["knowledge_base"]
    kb.search_fail_on = "vector_index"
    kb.search_fail_code = 68
    # ensure_indexes must not raise
    _run_ensure(db)


def test_TC_03_081_namespace_precreated_when_missing() -> None:
    db = _FakeDB()  # no preexisting namespaces
    _run_ensure(db)
    # Each collection that needs search-index DDL was pre-created
    for name in ("knowledge_base", "llm_cache", "long_term_memory"):
        assert name in db.created
