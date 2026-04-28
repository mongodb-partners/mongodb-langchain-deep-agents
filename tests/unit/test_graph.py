"""Sub-phase 12: deep-agent graph composition."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    from deep_agent import config, graph, models

    config.get_settings.cache_clear()
    models.get_llm.cache_clear()
    # The per-domain build_graph cache must not bleed between tests.
    graph.build_graph.cache_clear()


def test_TC_12_010_build_graph_invokes_create_deep_agent() -> None:
    from deep_agent import graph as graph_mod

    fake_graph = MagicMock()
    fake_checkpointer = object()
    fake_store = object()
    fake_llm = MagicMock()

    with patch("deep_agent.graph.create_deep_agent", return_value=fake_graph) as cda, patch(
        "deep_agent.graph.get_llm", return_value=fake_llm
    ), patch(
        "deep_agent.graph.build_checkpointer", return_value=fake_checkpointer
    ), patch("deep_agent.graph.build_store", return_value=fake_store), patch(
        "deep_agent.graph.install_semantic_cache"
    ), patch("deep_agent.graph.get_data_tools", return_value=[]):
        result = graph_mod.build_graph()

    assert result is fake_graph
    cda.assert_called_once()
    _, kwargs = cda.call_args
    assert kwargs["model"] is fake_llm
    assert kwargs["checkpointer"] is fake_checkpointer
    assert kwargs["store"] is fake_store
    assert kwargs["system_prompt"]
    assert kwargs["subagents"]
    # Main agent tools include KB + KG + fetch_and_cache (plus data toolkit output).
    tool_names = {_tool_name(t) for t in kwargs["tools"]}
    assert {"knowledge_base_search", "knowledge_base_hybrid_search",
            "knowledge_graph_search", "fetch_and_cache"} <= tool_names


def test_TC_20_070_build_graph_wires_mongo_backend_instance() -> None:
    """build_graph must pass a MongoVfsBackend INSTANCE (not a factory callable)
    to create_deep_agent so deepagents 0.7+ keeps working. Ref: spec 300."""
    from deep_agent import graph as graph_mod
    from deep_agent.backends.mongo_backend import MongoVfsBackend

    with patch("deep_agent.graph.create_deep_agent") as cda, patch(
        "deep_agent.graph.get_llm", return_value=MagicMock()
    ), patch("deep_agent.graph.build_checkpointer", return_value=object()), patch(
        "deep_agent.graph.build_store", return_value=object()
    ), patch("deep_agent.graph.install_semantic_cache"), patch(
        "deep_agent.graph.get_data_tools", return_value=[]
    ):
        graph_mod.build_graph()

    _, kwargs = cda.call_args
    backend = kwargs.get("backend")
    assert isinstance(backend, MongoVfsBackend), (
        f"backend must be a MongoVfsBackend instance, got {type(backend).__name__}"
    )
    # It must NOT be a bare callable (the old factory).
    assert not (callable(backend) and not isinstance(backend, MongoVfsBackend))


def test_TC_12_020_researcher_subagent_has_expected_tools() -> None:
    from deep_agent.agents.subagents import researcher_subagent

    sub = researcher_subagent()
    names = {_tool_name(t) for t in sub["tools"]}
    assert {
        "web_search",
        "fetch_and_cache",
        "knowledge_base_search",
        "knowledge_base_hybrid_search",
        "knowledge_graph_search",
    } <= names


def test_TC_12_021_researcher_subagent_dict_valid() -> None:
    from deep_agent.agents.subagents import researcher_subagent

    sub = researcher_subagent()
    assert sub["name"] == "researcher"
    assert sub["description"]
    assert sub["system_prompt"]


def test_TC_12_030_graph_gets_mongodb_saver_and_store() -> None:
    from deep_agent import graph as graph_mod

    saver = object()
    store = object()
    with patch("deep_agent.graph.create_deep_agent") as cda, patch(
        "deep_agent.graph.get_llm", return_value=MagicMock()
    ), patch(
        "deep_agent.graph.build_checkpointer", return_value=saver
    ), patch("deep_agent.graph.build_store", return_value=store), patch(
        "deep_agent.graph.install_semantic_cache"
    ), patch("deep_agent.graph.get_data_tools", return_value=[]):
        graph_mod.build_graph()

    _, kwargs = cda.call_args
    assert kwargs["checkpointer"] is saver
    assert kwargs["store"] is store


def test_TC_12_040_cache_install_best_effort() -> None:
    from deep_agent import graph as graph_mod

    with patch("deep_agent.graph.create_deep_agent", return_value=MagicMock()) as cda, patch(
        "deep_agent.graph.get_llm", return_value=MagicMock()
    ), patch("deep_agent.graph.build_checkpointer", return_value=object()), patch(
        "deep_agent.graph.build_store", return_value=object()
    ), patch(
        "deep_agent.graph.install_semantic_cache", side_effect=RuntimeError("down")
    ), patch("deep_agent.graph.get_data_tools", return_value=[]):
        # Must not raise
        graph_mod.build_graph()
    cda.assert_called_once()


def test_TC_12_070_build_graph_uncheckpointed_has_no_persistence() -> None:
    from deep_agent import graph as graph_mod

    with patch("deep_agent.graph.create_deep_agent") as cda, patch(
        "deep_agent.graph.get_llm", return_value=MagicMock()
    ), patch("deep_agent.graph.get_data_tools", return_value=[]):
        graph_mod.build_graph_uncheckpointed()

    _, kwargs = cda.call_args
    # Unchecked variant must not pass checkpointer or store
    assert kwargs.get("checkpointer") is None
    assert kwargs.get("store") is None


def test_TC_12_060_persist_plan_snapshot_maps_content_to_text() -> None:
    from unittest.mock import patch as _patch

    import mongomock

    from deep_agent.persistence.plans import persist_plan_snapshot

    db = mongomock.MongoClient()["deep_agent_test"]
    db["plans"].create_index(
        [("user_id", 1), ("thread_id", 1)], unique=True, name="plans_user_thread_unique"
    )
    state = {
        "todos": [
            {"id": "1", "content": "Outline report", "status": "in_progress"},
            {"id": "2", "content": "Draft executive summary", "status": "pending"},
        ]
    }
    with _patch("deep_agent.persistence.plans.get_db", return_value=db):
        persist_plan_snapshot(state, user_id="alice", thread_id="t1")

    doc = db["plans"].find_one({"user_id": "alice", "thread_id": "t1"})
    assert doc is not None
    assert [t["text"] for t in doc["todos"]] == ["Outline report", "Draft executive summary"]
    assert doc["todos"][0]["status"] == "in_progress"


def test_TC_12_061_persist_plan_snapshot_swallows_mongo_errors() -> None:
    from pymongo.errors import PyMongoError

    from deep_agent.persistence.plans import persist_plan_snapshot

    failing = MagicMock()
    failing.find_one.side_effect = PyMongoError("down")
    failing.update_one.side_effect = PyMongoError("down")
    db = MagicMock()
    db.__getitem__.return_value = failing
    with patch("deep_agent.persistence.plans.get_db", return_value=db):
        # Must not raise
        persist_plan_snapshot(
            {"todos": [{"id": "1", "content": "x"}]}, user_id="alice", thread_id="t1"
        )


# -------------------- Spec 400: per-domain graph cache --------------------


def test_TC_40_400_build_graph_cache_keyed_by_domain() -> None:
    """REQ-E-400: build_graph(domain) caches per domain. Distinct domains
    produce distinct compiled graphs; same domain returns the cached graph."""
    from deep_agent import graph as graph_mod

    graph_mod.build_graph.cache_clear()
    with patch("deep_agent.graph.create_deep_agent") as cda, patch(
        "deep_agent.graph.get_llm", return_value=MagicMock()
    ), patch(
        "deep_agent.graph.build_checkpointer", return_value=object()
    ), patch("deep_agent.graph.build_store", return_value=object()), patch(
        "deep_agent.graph.install_semantic_cache"
    ), patch("deep_agent.graph.get_data_tools", return_value=[]):
        cda.side_effect = lambda **_k: object()

        # Write a minimal custom pack so get_active_pack() works for test names.
        # Two distinct domain keys must not share a cached graph.
        with patch(
            "deep_agent.graph.get_active_pack",
            side_effect=lambda d=None: MagicMock(prompts=MagicMock(main="m")),
        ), patch(
            "deep_agent.graph.researcher_subagent",
            return_value={"name": "researcher"},
        ):
            a1 = graph_mod.build_graph(domain="pack_a")
            a2 = graph_mod.build_graph(domain="pack_a")
            b = graph_mod.build_graph(domain="pack_b")

    assert a1 is a2
    assert a1 is not b
    # Two distinct cache keys → create_deep_agent called exactly twice.
    assert cda.call_count == 2


def test_TC_40_400_build_graph_no_arg_uses_env_and_installs_cache() -> None:
    """INV-402 / REQ-E-401: no-arg build_graph() continues to install the
    process-global semantic cache (CLI / worker path) and binds to Settings."""
    from deep_agent import graph as graph_mod

    graph_mod.build_graph.cache_clear()
    with patch("deep_agent.graph.create_deep_agent", return_value=object()), patch(
        "deep_agent.graph.get_llm", return_value=MagicMock()
    ), patch(
        "deep_agent.graph.build_checkpointer", return_value=object()
    ) as bck, patch(
        "deep_agent.graph.build_store", return_value=object()
    ) as bst, patch("deep_agent.graph.install_semantic_cache") as inst, patch(
        "deep_agent.graph.get_data_tools", return_value=[]):
        graph_mod.build_graph()

    inst.assert_called_once()
    # No-arg path passes db_name=None (CLI/worker behavior preserved).
    _, kwargs = bck.call_args
    assert kwargs == {"db_name": None}
    _, kwargs = bst.call_args
    assert kwargs == {"db_name": None}


def test_TC_40_400_build_graph_with_domain_skips_global_cache_install() -> None:
    """REQ-E-422: per-domain graph build does NOT install the global semantic
    cache (the web server path is cacheless per D-404)."""
    from deep_agent import graph as graph_mod

    graph_mod.build_graph.cache_clear()
    with patch("deep_agent.graph.create_deep_agent", return_value=object()), patch(
        "deep_agent.graph.get_llm", return_value=MagicMock()
    ), patch(
        "deep_agent.graph.build_checkpointer", return_value=object()
    ), patch(
        "deep_agent.graph.build_store", return_value=object()
    ), patch("deep_agent.graph.install_semantic_cache") as inst, patch(
        "deep_agent.graph.get_data_tools", return_value=[]
    ), patch(
        "deep_agent.graph.get_active_pack",
        side_effect=lambda d=None: MagicMock(prompts=MagicMock(main="m")),
    ), patch(
        "deep_agent.graph.researcher_subagent", return_value={"name": "researcher"}
    ):
        graph_mod.build_graph(domain="pack_a")

    inst.assert_not_called()


def test_TC_40_400_build_graph_with_domain_passes_db_name_to_builders() -> None:
    """REQ-E-411: per-domain graph build routes db_name to checkpointer + store
    + data tools via db_for(domain)."""
    from deep_agent import graph as graph_mod

    graph_mod.build_graph.cache_clear()
    with patch("deep_agent.graph.create_deep_agent", return_value=object()), patch(
        "deep_agent.graph.get_llm", return_value=MagicMock()
    ), patch(
        "deep_agent.graph.build_checkpointer", return_value=object()
    ) as bck, patch(
        "deep_agent.graph.build_store", return_value=object()
    ) as bst, patch("deep_agent.graph.install_semantic_cache"), patch(
        "deep_agent.graph.get_data_tools", return_value=[]
    ) as gdt, patch(
        "deep_agent.graph.get_active_pack",
        side_effect=lambda d=None: MagicMock(prompts=MagicMock(main="m")),
    ), patch(
        "deep_agent.graph.researcher_subagent", return_value={"name": "researcher"}
    ):
        graph_mod.build_graph(domain="pack_a")

    # All three builders received the per-domain db name.
    _, kwargs = bck.call_args
    assert kwargs == {"db_name": "deep_agent_test_pack_a"}
    _, kwargs = bst.call_args
    assert kwargs == {"db_name": "deep_agent_test_pack_a"}
    _, kwargs = gdt.call_args
    assert kwargs == {"domain": "pack_a", "db_name": "deep_agent_test_pack_a"}


def _tool_name(t: Any) -> str:
    # Tools produced by @langchain_core.tools.tool expose `.name`; safety-wrapped tools too.
    return getattr(t, "name", "") or ""
