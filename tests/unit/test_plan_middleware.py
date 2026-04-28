"""Sub-phase 17: PlanPersistenceMiddleware.

Intercepts every ``after_model`` hook; when the LLM has updated the todo
list, upserts the plan into MongoDB immediately — no waiting for turn end.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import mongomock
import pytest


@pytest.fixture
def plans_db() -> Any:
    db = mongomock.MongoClient()["deep_agent_test"]
    db["plans"].create_index(
        [("user_id", 1), ("thread_id", 1)], unique=True, name="plans_user_thread_unique"
    )
    return db


@pytest.fixture(autouse=True)
def _patch_get_db(plans_db: Any):  # type: ignore[no-untyped-def]
    with patch("deep_agent.persistence.plans.get_db", return_value=plans_db):
        yield plans_db


@pytest.fixture(autouse=True)
def _clear_settings() -> None:
    from deep_agent import config

    config.get_settings.cache_clear()


def _runtime(user_id: str = "alice", thread_id: str = "t1") -> MagicMock:
    runtime = MagicMock()
    runtime.context = None
    runtime.config = {"configurable": {"user_id": user_id, "thread_id": thread_id}}
    return runtime


def test_TC_17_010_after_model_upserts_plan_from_state(plans_db: Any) -> None:
    from deep_agent.middleware.plan import PlanPersistenceMiddleware

    mw = PlanPersistenceMiddleware()
    state = {
        "todos": [
            {"id": "1", "content": "outline", "status": "in_progress"},
            {"id": "2", "content": "draft", "status": "pending"},
        ]
    }
    mw.after_model(state, _runtime(user_id="alice", thread_id="t1"))

    doc = plans_db["plans"].find_one({"user_id": "alice", "thread_id": "t1"})
    assert doc is not None
    assert [t["text"] for t in doc["todos"]] == ["outline", "draft"]
    assert doc["todos"][0]["status"] == "in_progress"


def test_TC_17_011_after_model_skips_when_no_todos(plans_db: Any) -> None:
    from deep_agent.middleware.plan import PlanPersistenceMiddleware

    mw = PlanPersistenceMiddleware()
    mw.after_model({"messages": []}, _runtime())
    assert plans_db["plans"].count_documents({}) == 0


def test_TC_17_012_after_model_skips_when_unchanged() -> None:
    """Consecutive calls with the same todo list must only upsert once."""
    from deep_agent.middleware.plan import PlanPersistenceMiddleware

    mw = PlanPersistenceMiddleware()
    with patch("deep_agent.middleware.plan.save_plan") as save:
        mw.after_model(
            {"todos": [{"id": "1", "content": "x", "status": "pending"}]},
            _runtime(),
        )
        mw.after_model(
            {"todos": [{"id": "1", "content": "x", "status": "pending"}]},
            _runtime(),
        )

    assert save.call_count == 1


def test_TC_17_013_after_model_persists_on_change() -> None:
    """Status/text changes between turns trigger a second upsert."""
    from deep_agent.middleware.plan import PlanPersistenceMiddleware

    mw = PlanPersistenceMiddleware()
    with patch("deep_agent.middleware.plan.save_plan") as save:
        mw.after_model(
            {"todos": [{"id": "1", "content": "x", "status": "pending"}]},
            _runtime(),
        )
        mw.after_model(
            {"todos": [{"id": "1", "content": "x", "status": "in_progress"}]},
            _runtime(),
        )

    assert save.call_count == 2


def test_TC_17_014_after_model_swallows_mongo_errors() -> None:
    """PyMongoError must not fail the turn."""
    from pymongo.errors import PyMongoError

    from deep_agent.middleware.plan import PlanPersistenceMiddleware

    mw = PlanPersistenceMiddleware()
    with patch(
        "deep_agent.middleware.plan.save_plan", side_effect=PyMongoError("down")
    ):
        # Must not raise
        result = mw.after_model(
            {"todos": [{"id": "1", "content": "x", "status": "pending"}]},
            _runtime(),
        )
    assert result is None


def test_TC_17_015_after_model_requires_user_and_thread_id() -> None:
    """Without both IDs, middleware is a no-op (best-effort, never raises)."""
    from deep_agent.middleware.plan import PlanPersistenceMiddleware

    mw = PlanPersistenceMiddleware()
    runtime = MagicMock()
    runtime.config = {"configurable": {}}

    with patch("deep_agent.middleware.plan.save_plan") as save:
        mw.after_model(
            {"todos": [{"id": "1", "content": "x", "status": "pending"}]}, runtime
        )
    save.assert_not_called()


def test_TC_17_020_graph_wires_plan_middleware() -> None:
    """build_graph must pass an instance of PlanPersistenceMiddleware
    via the deepagents ``middleware`` argument."""
    from deep_agent import graph as graph_mod
    from deep_agent.middleware.plan import PlanPersistenceMiddleware

    with patch("deep_agent.graph.create_deep_agent") as cda, patch(
        "deep_agent.graph.get_llm", return_value=MagicMock()
    ), patch("deep_agent.graph.build_checkpointer", return_value=object()), patch(
        "deep_agent.graph.build_store", return_value=object()
    ), patch("deep_agent.graph.install_semantic_cache"), patch(
        "deep_agent.graph.get_data_tools", return_value=[]
    ):
        graph_mod.build_graph()

    _, kwargs = cda.call_args
    middleware = list(kwargs.get("middleware") or [])
    assert any(isinstance(m, PlanPersistenceMiddleware) for m in middleware)
