"""Sub-phase 08: KB search tools."""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    from deep_agent import config, models

    config.get_settings.cache_clear()
    models.get_llm.cache_clear()
    models.get_embeddings.cache_clear()
    models.get_reranker.cache_clear()


def _identity_rerank(docs: list[Any], _q: str) -> list[Any]:
    return docs


# -------------------- Hardening: KB search must be best-effort --------------------


def test_TC_08_015_kb_search_returns_sentinel_on_operation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KB search must NOT raise when Atlas $vectorSearch fails (missing index,
    empty collection, transient Atlas error). A raise leaves the parent
    agent's ``tool_use`` block without a ``tool_result``, which Bedrock's
    strict validator rejects at the next turn. Return a sentinel instead.
    """
    from pymongo.errors import OperationFailure

    from deep_agent.tools import knowledge_base_search as kbs

    class _FakeVS:
        def similarity_search(self, _q: str, **_k: Any) -> list[Any]:
            raise OperationFailure("$vectorSearch index not found")

    monkeypatch.setattr(kbs, "_vector_store", lambda db_name=None: _FakeVS())

    out = kbs.knowledge_base_search.invoke({"query": "anything"})
    # Returns a string sentinel (not a list) — "No results." via _hits_to_string.
    assert isinstance(out, str)
    assert "No results" in out or out == "No results."


def test_TC_08_016_kb_search_returns_sentinel_on_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any exception from the underlying retriever must be caught — the tool
    is not the right layer to decide whether the caller can retry."""
    from deep_agent.tools import knowledge_base_search as kbs

    class _FakeVS:
        def similarity_search(self, _q: str, **_k: Any) -> list[Any]:
            raise RuntimeError("connection reset by peer")

    monkeypatch.setattr(kbs, "_vector_store", lambda db_name=None: _FakeVS())

    out = kbs.knowledge_base_search.invoke({"query": "anything"})
    assert isinstance(out, str)  # must not raise


def test_TC_08_025_kb_hybrid_returns_sentinel_on_operation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hybrid retriever has the same failure mode when the Atlas Search index
    is missing — same hardening required."""
    from pymongo.errors import OperationFailure

    from deep_agent.tools import knowledge_base_search as kbs

    class _FakeHybrid:
        def invoke(self, _q: str) -> list[Any]:
            raise OperationFailure("search index not found")

    monkeypatch.setattr(kbs, "_hybrid_retriever", lambda db_name=None: _FakeHybrid())

    out = kbs.knowledge_base_hybrid_search.invoke({"query": "anything"})
    assert isinstance(out, str)


def test_TC_08_026_kb_hybrid_returns_sentinel_on_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deep_agent.tools import knowledge_base_search as kbs

    class _FakeHybrid:
        def invoke(self, _q: str) -> list[Any]:
            raise RuntimeError("atlas search down")

    monkeypatch.setattr(kbs, "_hybrid_retriever", lambda db_name=None: _FakeHybrid())

    out = kbs.knowledge_base_hybrid_search.invoke({"query": "anything"})
    assert isinstance(out, str)


# -------------------- Spec 400: domain-aware vector store caching --------------------


def test_TC_40_413_kb_vector_store_keyed_by_db_name() -> None:
    """REQ-E-413: _vector_store(db_name=...) caches per db_name so concurrent
    cross-domain requests get distinct stores."""
    from deep_agent.tools import knowledge_base_search as kbs

    kbs._vector_store.cache_clear()
    with patch(
        "deep_agent.tools.knowledge_base_search.build_vector_store"
    ) as build:
        build.side_effect = lambda db_name=None: object()
        a1 = kbs._vector_store("deep_agent_a")
        a2 = kbs._vector_store("deep_agent_a")
        b = kbs._vector_store("deep_agent_b")
        c = kbs._vector_store()  # no-arg path caches separately under None
    assert a1 is a2
    assert a1 is not b
    assert a1 is not c
    # Three distinct keys → three builder calls.
    assert build.call_count == 3
    seen = [call.kwargs.get("db_name") for call in build.call_args_list]
    assert seen == ["deep_agent_a", "deep_agent_b", None]


def test_TC_40_413_kb_search_reads_db_name_from_runtime_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REQ-E-413: ``knowledge_base_search`` resolves the vector store from the
    db_name injected into RunnableConfig.configurable (set by /chat handler)."""
    from langchain_core.documents import Document

    from deep_agent.tools import knowledge_base_search as kbs

    captured_db: list[str | None] = []

    class _FakeVS:
        def similarity_search(self, _q: str, **_k: Any) -> list[Document]:
            return [Document(page_content="x", metadata={})]

    def _fake_build(db_name: str | None = None) -> _FakeVS:
        captured_db.append(db_name)
        return _FakeVS()

    monkeypatch.setattr(kbs, "build_vector_store", _fake_build)
    kbs._vector_store.cache_clear()
    rer = MagicMock()
    rer.compress_documents.side_effect = _identity_rerank
    monkeypatch.setattr(kbs, "get_reranker", lambda: rer)

    # Invoke with a RunnableConfig carrying db_name.
    kbs.knowledge_base_search.invoke(
        {"query": "q"},
        config={"configurable": {"db_name": "deep_agent_pack_a"}},
    )
    assert captured_db == ["deep_agent_pack_a"]


def test_TC_40_413_kb_search_falls_back_to_settings_without_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a config/db_name, KB search uses Settings.mongodb_db (no override)."""
    from langchain_core.documents import Document

    from deep_agent.tools import knowledge_base_search as kbs

    captured_db: list[str | None] = []

    class _FakeVS:
        def similarity_search(self, _q: str, **_k: Any) -> list[Document]:
            return []

    def _fake_build(db_name: str | None = None) -> _FakeVS:
        captured_db.append(db_name)
        return _FakeVS()

    monkeypatch.setattr(kbs, "build_vector_store", _fake_build)
    kbs._vector_store.cache_clear()
    rer = MagicMock()
    rer.compress_documents.side_effect = _identity_rerank
    monkeypatch.setattr(kbs, "get_reranker", lambda: rer)

    kbs.knowledge_base_search.invoke({"query": "q"})
    # No config → None flows through to build_vector_store, which then reads Settings.
    assert captured_db == [None]


def test_TC_08_010_kb_search_forwards_pre_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    from langchain_core.documents import Document

    from deep_agent.tools import knowledge_base_search as kbs

    captured: dict[str, Any] = {}

    class _FakeVS:
        def similarity_search(self, query: str, **kwargs: Any) -> list[Document]:
            captured.update(kwargs)
            return [Document(page_content="ok", metadata={"source": "runbook"})]

    monkeypatch.setattr(kbs, "_vector_store", lambda db_name=None: _FakeVS())
    rer = MagicMock()
    rer.compress_documents.side_effect = _identity_rerank
    monkeypatch.setattr(kbs, "get_reranker", lambda: rer)

    out = kbs.knowledge_base_search.invoke({"query": "disk full", "k": 2, "source": "runbook"})
    # Tool now returns a JSON string, not a list.
    assert isinstance(out, str)
    parsed = json.loads(out)
    assert parsed == [{"text": "ok", "metadata": {"source": "runbook"}}]
    assert captured.get("pre_filter") == {"metadata.source": {"$eq": "runbook"}}
    assert captured.get("k") == 6


def test_TC_08_011_kb_search_omits_pre_filter_when_source_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langchain_core.documents import Document

    from deep_agent.tools import knowledge_base_search as kbs

    captured: dict[str, Any] = {}

    class _FakeVS:
        def similarity_search(self, query: str, **kwargs: Any) -> list[Document]:
            captured.update(kwargs)
            return []

    monkeypatch.setattr(kbs, "_vector_store", lambda db_name=None: _FakeVS())
    rer = MagicMock()
    rer.compress_documents.side_effect = _identity_rerank
    monkeypatch.setattr(kbs, "get_reranker", lambda: rer)

    kbs.knowledge_base_search.invoke({"query": "q"})
    assert "pre_filter" not in captured


def test_TC_08_020_hybrid_retriever_uses_mongodb_class() -> None:
    from deep_agent.tools.knowledge_base_search import build_hybrid_retriever

    with patch("deep_agent.tools.knowledge_base_search._vector_store") as vs, patch(
        "langchain_mongodb.retrievers.MongoDBAtlasHybridSearchRetriever"
    ) as hyb:
        vs.return_value = object()
        build_hybrid_retriever.cache_clear()
        build_hybrid_retriever()

    hyb.assert_called_once()
    _, kwargs = hyb.call_args
    assert kwargs["search_index_name"] == "search_index"


def test_TC_08_021_hybrid_tool_returns_dicts(monkeypatch: pytest.MonkeyPatch) -> None:
    from langchain_core.documents import Document

    from deep_agent.tools import knowledge_base_search as kbs

    class _FakeHybrid:
        def invoke(self, query: str) -> list[Document]:
            return [Document(page_content="hit", metadata={"source": "h"})]

    monkeypatch.setattr(kbs, "_hybrid_retriever", lambda db_name=None: _FakeHybrid())
    rer = MagicMock()
    rer.compress_documents.side_effect = _identity_rerank
    monkeypatch.setattr(kbs, "get_reranker", lambda: rer)

    out = kbs.knowledge_base_hybrid_search.invoke({"query": "xyz"})
    # Tool returns a JSON string now.
    assert isinstance(out, str)
    parsed = json.loads(out)
    assert parsed == [{"text": "hit", "metadata": {"source": "h"}}]


def test_TC_08_030_rerank_applied_and_trims_to_k(monkeypatch: pytest.MonkeyPatch) -> None:
    from langchain_core.documents import Document

    from deep_agent.tools import knowledge_base_search as kbs

    docs = [
        Document(page_content="low", metadata={}),
        Document(page_content="mid", metadata={}),
        Document(page_content="high", metadata={}),
    ]

    class _FakeVS:
        def similarity_search(self, query: str, **kwargs: Any) -> list[Document]:
            return list(docs)

    captured: dict[str, Any] = {}

    def _rerank(d: list[Any], q: str) -> list[Any]:
        captured["count"] = len(d)
        return list(reversed(d))

    rer = MagicMock()
    rer.compress_documents.side_effect = _rerank
    monkeypatch.setattr(kbs, "_vector_store", lambda db_name=None: _FakeVS())
    monkeypatch.setattr(kbs, "get_reranker", lambda: rer)

    out = kbs.knowledge_base_search.invoke({"query": "q", "k": 2})
    assert captured["count"] == 3
    parsed = json.loads(out)
    assert [d["text"] for d in parsed] == ["high", "mid"]


def test_TC_08_040_rerank_fallback_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    from langchain_core.documents import Document

    from deep_agent.tools import knowledge_base_search as kbs

    class _FakeVS:
        def similarity_search(self, query: str, **kwargs: Any) -> list[Document]:
            return [
                Document(page_content="a", metadata={}),
                Document(page_content="b", metadata={}),
                Document(page_content="c", metadata={}),
            ]

    rer = MagicMock()
    rer.compress_documents.side_effect = RuntimeError("rerank down")
    monkeypatch.setattr(kbs, "_vector_store", lambda db_name=None: _FakeVS())
    monkeypatch.setattr(kbs, "get_reranker", lambda: rer)

    out = kbs.knowledge_base_search.invoke({"query": "q", "k": 2})
    parsed = json.loads(out)
    assert [d["text"] for d in parsed] == ["a", "b"]


def test_TC_08_041_rerank_skipped_on_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    from deep_agent.tools import knowledge_base_search as kbs

    class _FakeVS:
        def similarity_search(self, query: str, **kwargs: Any) -> list[Any]:
            return []

    rer = MagicMock()
    monkeypatch.setattr(kbs, "_vector_store", lambda db_name=None: _FakeVS())
    monkeypatch.setattr(kbs, "get_reranker", lambda: rer)

    out = kbs.knowledge_base_search.invoke({"query": "q"})
    assert isinstance(out, str)
    assert "No results" in out
    rer.compress_documents.assert_not_called()


def test_TC_08_050_hybrid_uses_rerank(monkeypatch: pytest.MonkeyPatch) -> None:
    from langchain_core.documents import Document

    from deep_agent.tools import knowledge_base_search as kbs

    class _FakeHybrid:
        def invoke(self, _: str) -> list[Document]:
            return [
                Document(page_content="x1", metadata={}),
                Document(page_content="x2", metadata={}),
            ]

    rer = MagicMock()
    rer.compress_documents.side_effect = lambda d, q: list(reversed(d))
    monkeypatch.setattr(kbs, "_hybrid_retriever", lambda db_name=None: _FakeHybrid())
    monkeypatch.setattr(kbs, "get_reranker", lambda: rer)

    out = kbs.knowledge_base_hybrid_search.invoke({"query": "q"})
    parsed = json.loads(out)
    assert [d["text"] for d in parsed] == ["x2", "x1"]
