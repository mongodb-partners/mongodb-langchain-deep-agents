"""Sub-phase 11: plans persistence."""
from __future__ import annotations

import time
from typing import Any
from unittest.mock import patch

import pytest


@pytest.fixture
def plans_db() -> Any:
    """Fresh mongomock DB with the same unique index ensure_indexes() creates."""
    import mongomock

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


def test_TC_11_010_fresh_save_inserts_document() -> None:
    from deep_agent.persistence.plans import TodoItem, save_plan

    doc = save_plan(
        "alice",
        "t1",
        [TodoItem(id="1", text="Outline report")],
    )
    assert doc.user_id == "alice"
    assert doc.thread_id == "t1"
    assert [t.text for t in doc.todos] == ["Outline report"]
    assert doc.created_at is not None
    assert doc.updated_at is not None


def test_TC_11_011_upsert_preserves_created_at_advances_updated_at() -> None:
    from deep_agent.persistence.plans import TodoItem, save_plan

    first = save_plan("alice", "t1", [TodoItem(id="1", text="a")])
    time.sleep(0.01)
    second = save_plan(
        "alice",
        "t1",
        [TodoItem(id="1", text="a", status="completed")],
    )
    assert second.created_at == first.created_at
    assert second.updated_at >= first.updated_at


def test_TC_11_012_accepts_raw_dict_todos() -> None:
    from deep_agent.persistence.plans import save_plan

    doc = save_plan(
        "alice",
        "t1",
        [{"id": "1", "text": "from dict", "status": "in_progress"}],
    )
    assert doc.todos[0].status == "in_progress"
    assert doc.todos[0].text == "from dict"


def test_TC_11_020_load_returns_prior_plan() -> None:
    from deep_agent.persistence.plans import TodoItem, load_plan, save_plan

    save_plan(
        "alice",
        "t1",
        [TodoItem(id="1", text="a"), TodoItem(id="2", text="b", status="completed")],
    )
    loaded = load_plan("alice", "t1")
    assert loaded is not None
    assert [t.id for t in loaded.todos] == ["1", "2"]
    assert loaded.todos[1].status == "completed"


def test_TC_11_021_load_missing_returns_none() -> None:
    from deep_agent.persistence.plans import load_plan

    assert load_plan("nobody", "nothread") is None


def test_TC_11_030_different_keys_are_isolated() -> None:
    from deep_agent.persistence.plans import TodoItem, load_plan, save_plan

    save_plan("alice", "t1", [TodoItem(id="1", text="alice-t1")])
    save_plan("bob", "t1", [TodoItem(id="1", text="bob-t1")])
    save_plan("alice", "t2", [TodoItem(id="1", text="alice-t2")])

    a_t1 = load_plan("alice", "t1")
    b_t1 = load_plan("bob", "t1")
    a_t2 = load_plan("alice", "t2")
    assert a_t1 and a_t1.todos[0].text == "alice-t1"
    assert b_t1 and b_t1.todos[0].text == "bob-t1"
    assert a_t2 and a_t2.todos[0].text == "alice-t2"


def test_TC_11_040_delete_plan() -> None:
    from deep_agent.persistence.plans import TodoItem, delete_plan, load_plan, save_plan

    save_plan("alice", "t1", [TodoItem(id="1", text="a")])
    assert delete_plan("alice", "t1") is True
    assert load_plan("alice", "t1") is None
    assert delete_plan("alice", "t1") is False


# -------------------- Spec 400: db_name plumbing + load_plan_snapshot --------------------


def test_TC_40_411_save_plan_routes_to_db_name() -> None:
    """REQ-E-411: save_plan(db_name=...) writes into the named DB."""
    import mongomock

    from deep_agent.persistence.plans import TodoItem, save_plan

    # Two distinct mongomock DBs to verify routing.
    client = mongomock.MongoClient()
    pack_a = client["deep_agent_pack_a"]
    pack_b = client["deep_agent_pack_b"]
    for db in (pack_a, pack_b):
        db["plans"].create_index(
            [("user_id", 1), ("thread_id", 1)],
            unique=True,
            name="plans_user_thread_unique",
        )

    def _fake_get_db(db_name: str | None = None) -> Any:
        if db_name == "deep_agent_pack_a":
            return pack_a
        if db_name == "deep_agent_pack_b":
            return pack_b
        raise AssertionError(f"unexpected db_name: {db_name!r}")

    with patch("deep_agent.persistence.plans.get_db", side_effect=_fake_get_db):
        save_plan(
            "alice", "t1",
            [TodoItem(id="1", text="pack-a plan")],
            db_name="deep_agent_pack_a",
        )
        save_plan(
            "alice", "t1",
            [TodoItem(id="1", text="pack-b plan")],
            db_name="deep_agent_pack_b",
        )

    a_doc = pack_a["plans"].find_one({"user_id": "alice", "thread_id": "t1"})
    b_doc = pack_b["plans"].find_one({"user_id": "alice", "thread_id": "t1"})
    assert a_doc and a_doc["todos"][0]["text"] == "pack-a plan"
    assert b_doc and b_doc["todos"][0]["text"] == "pack-b plan"


def test_TC_40_440_load_plan_snapshot_returns_todos_and_updated_at(
    plans_db: Any,
) -> None:
    """REQ-E-440: load_plan_snapshot returns {todos, updated_at} for /plans."""
    from deep_agent.persistence.plans import TodoItem, load_plan_snapshot, save_plan

    save_plan(
        "alice",
        "u1:pack_a:default",
        [
            TodoItem(id="1", text="Gather data", status="completed"),
            TodoItem(id="2", text="Draft writeup", status="in_progress"),
        ],
    )

    snap = load_plan_snapshot("alice", "u1:pack_a:default")
    assert isinstance(snap, dict)
    assert [t["id"] for t in snap["todos"]] == ["1", "2"]
    assert snap["todos"][0]["status"] == "completed"
    assert snap["todos"][1]["text"] == "Draft writeup"
    assert snap["updated_at"] is not None  # ISO string


def test_TC_40_EC_405_load_plan_snapshot_missing_returns_empty() -> None:
    """REQ-E-EC-405: missing snapshot returns ``{todos: [], updated_at: None}``
    (never 404 — the UI polls after every `done`)."""
    from deep_agent.persistence.plans import load_plan_snapshot

    snap = load_plan_snapshot("nobody", "nothread")
    assert snap == {"todos": [], "updated_at": None}


def test_TC_40_411_load_plan_snapshot_reads_from_db_name() -> None:
    """REQ-E-411: load_plan_snapshot(db_name=...) reads the named DB."""
    import mongomock

    from deep_agent.persistence.plans import TodoItem, load_plan_snapshot, save_plan

    client = mongomock.MongoClient()
    pack_a = client["deep_agent_pack_a"]
    pack_a["plans"].create_index(
        [("user_id", 1), ("thread_id", 1)],
        unique=True,
        name="plans_user_thread_unique",
    )

    with patch("deep_agent.persistence.plans.get_db", return_value=pack_a):
        save_plan(
            "alice", "t1",
            [TodoItem(id="1", text="pack-a snapshot")],
            db_name="deep_agent_pack_a",
        )
        snap = load_plan_snapshot(
            "alice", "t1", db_name="deep_agent_pack_a"
        )

    assert snap["todos"][0]["text"] == "pack-a snapshot"
