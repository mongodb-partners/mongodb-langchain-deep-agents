"""Sub-phase 08: knowledge_graph_search tool."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    from deep_agent import config

    config.get_settings.cache_clear()


def test_TC_08_060_kg_tool_delegates_to_chat_response() -> None:
    from deep_agent.tools import knowledge_graph_search as kgs

    class _Reply:
        content = "graph-answer"

    fake = MagicMock()
    fake.chat_response.return_value = _Reply()

    kgs._graph_store.cache_clear()
    with patch(
        "deep_agent.tools.knowledge_graph_search.build_graph_store", return_value=fake
    ):
        out = kgs.knowledge_graph_search.invoke({"query": "who knows whom?"})

    assert out == "graph-answer"
    fake.chat_response.assert_called_once_with("who knows whom?")
    kgs._graph_store.cache_clear()


def test_TC_08_061_kg_tool_returns_sentinel_on_operation_failure() -> None:
    from pymongo.errors import OperationFailure

    from deep_agent.tools import knowledge_graph_search as kgs

    fake = MagicMock()
    fake.chat_response.side_effect = OperationFailure("$in needs an array")

    kgs._graph_store.cache_clear()
    with patch(
        "deep_agent.tools.knowledge_graph_search.build_graph_store", return_value=fake
    ):
        out = kgs.knowledge_graph_search.invoke({"query": "anything"})

    assert "No matching entities" in out
    kgs._graph_store.cache_clear()


def test_TC_08_062_kg_tool_handles_string_return() -> None:
    from deep_agent.tools import knowledge_graph_search as kgs

    fake = MagicMock()
    fake.chat_response.return_value = "plain"

    kgs._graph_store.cache_clear()
    with patch(
        "deep_agent.tools.knowledge_graph_search.build_graph_store", return_value=fake
    ):
        out = kgs.knowledge_graph_search.invoke({"query": "anything"})

    assert out == "plain"
    kgs._graph_store.cache_clear()


# -------------------- Spec 400: domain-aware graph store --------------------


def test_TC_40_413_kg_graph_store_keyed_by_db_name() -> None:
    """REQ-E-413: _graph_store(db_name=...) caches per db_name."""
    from deep_agent.tools import knowledge_graph_search as kgs

    kgs._graph_store.cache_clear()
    with patch(
        "deep_agent.tools.knowledge_graph_search.build_graph_store"
    ) as build:
        build.side_effect = lambda db_name=None: object()
        a = kgs._graph_store("deep_agent_a")
        b = kgs._graph_store("deep_agent_b")
        a_again = kgs._graph_store("deep_agent_a")
    assert a is not b
    assert a is a_again
    assert build.call_count == 2


def test_TC_40_413_kg_search_reads_db_name_from_runtime_config() -> None:
    """REQ-E-413: ``knowledge_graph_search`` resolves the graph store from
    db_name injected into RunnableConfig.configurable."""
    from deep_agent.tools import knowledge_graph_search as kgs

    captured_db: list[str | None] = []

    class _FakeGS:
        def chat_response(self, _q: str) -> str:
            return "answer"

    def _fake_build(db_name: str | None = None) -> _FakeGS:
        captured_db.append(db_name)
        return _FakeGS()

    kgs._graph_store.cache_clear()
    with patch(
        "deep_agent.tools.knowledge_graph_search.build_graph_store",
        side_effect=_fake_build,
    ):
        result = kgs.knowledge_graph_search.invoke(
            {"query": "q"},
            config={"configurable": {"db_name": "deep_agent_pack_b"}},
        )
    assert result == "answer"
    assert captured_db == ["deep_agent_pack_b"]
    kgs._graph_store.cache_clear()
