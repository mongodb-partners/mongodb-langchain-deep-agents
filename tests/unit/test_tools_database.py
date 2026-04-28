"""Sub-phase 10: safety-wrapped MongoDBDatabaseToolkit."""
from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    from deep_agent import config, models

    config.get_settings.cache_clear()
    models.get_llm.cache_clear()


def test_TC_10_010_destructive_stage_refused() -> None:
    from deep_agent.tools.database_toolkit import QueryRefusedError, enforce_safety

    with pytest.raises(QueryRefusedError, match="destructive"):
        enforce_safety(
            "orders",
            json.dumps([{"$match": {"x": 1}}, {"$out": "leak"}]),
            {"orders"},
        )


def test_TC_10_020_destructive_keyword_refused() -> None:
    from deep_agent.tools.database_toolkit import QueryRefusedError, enforce_safety

    with pytest.raises(QueryRefusedError, match="destructive"):
        enforce_safety("orders", json.dumps([{"$match": {"drop": 1}}]), {"orders"})


def test_TC_10_030_underscore_prefix_refused() -> None:
    from deep_agent.tools.database_toolkit import QueryRefusedError, enforce_safety

    with pytest.raises(QueryRefusedError, match="underscore"):
        enforce_safety("_system", json.dumps([{"$match": {}}]), {"_system"})


def test_TC_10_040_allow_list_enforced() -> None:
    from deep_agent.tools.database_toolkit import QueryRefusedError, enforce_safety

    with pytest.raises(QueryRefusedError, match="disallowed"):
        enforce_safety("not_in_list", json.dumps([{"$match": {}}]), {"orders"})


def test_TC_10_050_implicit_limit_injected() -> None:
    from deep_agent.tools.database_toolkit import DEFAULT_PIPELINE_LIMIT, enforce_safety

    safe = enforce_safety("orders", json.dumps([{"$match": {"a": 1}}]), {"orders"})
    stages = json.loads(safe)
    assert stages[-1] == {"$limit": DEFAULT_PIPELINE_LIMIT}


def test_TC_10_051_limit_not_duplicated() -> None:
    from deep_agent.tools.database_toolkit import enforce_safety

    original = json.dumps([{"$match": {}}, {"$limit": 10}])
    safe = enforce_safety("orders", original, {"orders"})
    stages = json.loads(safe)
    assert sum(1 for s in stages if "$limit" in s) == 1


def test_TC_10_052_unparseable_pipeline_untouched() -> None:
    from deep_agent.tools.database_toolkit import enforce_safety

    raw = "not-json"
    assert enforce_safety("orders", raw, {"orders"}) == raw


def test_TC_10_060_toolkit_instantiated_with_db_and_llm() -> None:
    with patch("deep_agent.tools.database_toolkit.MongoDBDatabaseToolkit") as tk, patch(
        "deep_agent.tools.database_toolkit._database"
    ) as db, patch("deep_agent.tools.database_toolkit.get_llm") as gl:
        db.return_value = object()
        gl.return_value = object()
        from deep_agent.tools.database_toolkit import _toolkit

        _toolkit.cache_clear()
        _toolkit()
    tk.assert_called_once()
    _, kwargs = tk.call_args
    assert kwargs["db"] is db.return_value
    assert kwargs["llm"] is gl.return_value


def test_TC_10_061_get_data_tools_wraps_each_inner_tool() -> None:
    from langchain_core.tools import BaseTool

    class _Inner(BaseTool):
        name: str = "inner"
        description: str = "desc"

        def _run(self, *args: Any, **kwargs: Any) -> str:
            return "ok"

    fake_toolkit = MagicMock()
    fake_toolkit.get_tools.return_value = [_Inner(), _Inner()]

    from deep_agent.tools import database_toolkit as dbt

    dbt._toolkit.cache_clear()
    with patch("deep_agent.tools.database_toolkit._toolkit", return_value=fake_toolkit):
        tools = dbt.get_data_tools()

    assert len(tools) == 2
    assert all(isinstance(t, dbt._SafeToolWrapper) for t in tools)
    assert "safety-wrapped" in tools[0].description


def test_TC_10_062_safe_wrapper_refuses_unsafe_and_runs_safe() -> None:
    from langchain_core.tools import BaseTool

    from deep_agent.tools import database_toolkit as dbt

    captured: dict[str, Any] = {}

    class _Inner(BaseTool):
        name: str = "mongodb_query"
        description: str = "runs a query"

        def _run(self, *args: Any, **kwargs: Any) -> str:
            captured.clear()
            captured.update(kwargs)
            return "ran"

    wrapped = dbt._SafeToolWrapper(inner=_Inner(), allow_list={"orders"})

    # Unsafe: $out in pipeline
    result = wrapped._run(
        query=json.dumps([{"$out": "leak"}]), collection="orders"
    )
    assert isinstance(result, str) and result.startswith("QUERY REFUSED")
    assert captured == {}

    # Safe: pipeline with $match; implicit $limit injected
    out = wrapped._run(
        query=json.dumps([{"$match": {"ok": 1}}]), collection="orders"
    )
    assert out == "ran"
    stages = json.loads(captured["query"])
    assert stages[-1] == {"$limit": dbt.DEFAULT_PIPELINE_LIMIT}


def test_TC_10_063_safe_wrapper_arun_delegates_to_run() -> None:
    from langchain_core.tools import BaseTool

    from deep_agent.tools import database_toolkit as dbt

    class _Inner(BaseTool):
        name: str = "t"
        description: str = "d"

        def _run(self, *args: Any, **kwargs: Any) -> str:
            return "sync"

    wrapped = dbt._SafeToolWrapper(inner=_Inner(), allow_list={"orders"})
    loop = asyncio.new_event_loop()
    try:
        out = loop.run_until_complete(
            wrapped._arun(query=json.dumps([{"$match": {}}]), collection="orders")
        )
    finally:
        loop.close()
    assert out == "sync"


def test_TC_10_064_safe_wrapper_normalizes_pipeline_kwarg_and_positional() -> None:
    from langchain_core.tools import BaseTool

    from deep_agent.tools import database_toolkit as dbt

    captured: dict[str, Any] = {"args": (), "kwargs": {}}

    class _Inner(BaseTool):
        name: str = "mongodb_query"
        description: str = "d"

        def _run(self, *args: Any, **kwargs: Any) -> str:
            captured["args"] = args
            captured["kwargs"] = dict(kwargs)
            return "ok"

    wrapped = dbt._SafeToolWrapper(inner=_Inner(), allow_list={"orders"})

    wrapped._run(pipeline=json.dumps([{"$match": {}}]), collection="orders")
    stages = json.loads(captured["kwargs"]["pipeline"])
    assert stages[-1] == {"$limit": dbt.DEFAULT_PIPELINE_LIMIT}

    captured["args"] = ()
    captured["kwargs"] = {}
    wrapped._run(json.dumps([{"$match": {}}]), collection="orders")
    stages = json.loads(captured["args"][0])
    assert stages[-1] == {"$limit": dbt.DEFAULT_PIPELINE_LIMIT}


def test_TC_10_070_data_agent_uri_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONGODB_URI", "mongodb+srv://app@cluster/deep_agent")
    monkeypatch.setenv("DATA_AGENT_MONGODB_URI", "mongodb+srv://dataagent@cluster/deep_agent")
    from deep_agent import config

    config.get_settings.cache_clear()

    with patch("deep_agent.tools.database_toolkit.MongoDBDatabase") as mdb:
        from deep_agent.tools.database_toolkit import _database

        _database.cache_clear()
        _database()
    _, kwargs = mdb.from_connection_string.call_args
    assert kwargs["connection_string"] == "mongodb+srv://dataagent@cluster/deep_agent"


def test_TC_10_080_falls_back_to_mongodb_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONGODB_URI", "mongodb+srv://app@cluster/deep_agent")
    monkeypatch.delenv("DATA_AGENT_MONGODB_URI", raising=False)
    from deep_agent import config

    config.get_settings.cache_clear()

    with patch("deep_agent.tools.database_toolkit.MongoDBDatabase") as mdb:
        from deep_agent.tools.database_toolkit import _database

        _database.cache_clear()
        _database()
    _, kwargs = mdb.from_connection_string.call_args
    assert kwargs["connection_string"] == "mongodb+srv://app@cluster/deep_agent"


# -------------------- Spec 400: per-(domain, db_name) cache keys --------------------


def test_TC_40_412a_database_cache_keyed_by_db_name() -> None:
    """REQ-E-412: _database(db_name=...) caches per db_name; different names
    produce different MongoDBDatabase instances."""
    from deep_agent.tools import database_toolkit as dbt

    dbt._database.cache_clear()
    with patch("deep_agent.tools.database_toolkit.MongoDBDatabase") as mdb:
        mdb.from_connection_string.side_effect = lambda **_: object()
        a1 = dbt._database("deep_agent_a")
        a2 = dbt._database("deep_agent_a")
        b = dbt._database("deep_agent_b")
    # Cache hit on repeat.
    assert a1 is a2
    # Different key → new instance.
    assert a1 is not b
    # MongoDBDatabase.from_connection_string was called twice (once per distinct key).
    assert mdb.from_connection_string.call_count == 2
    calls = mdb.from_connection_string.call_args_list
    assert calls[0].kwargs["database"] == "deep_agent_a"
    assert calls[1].kwargs["database"] == "deep_agent_b"


def test_TC_40_412b_get_data_tools_uses_domain_and_db_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """REQ-E-412: get_data_tools(domain=..., db_name=...) wires the named pack's
    allow-list into the wrapper and the named DB into the toolkit."""
    # Build a minimal custom pack on disk with a distinctive allow_list.
    import yaml

    pack = tmp_path / "mypack"
    (pack / "seeds" / "operational").mkdir(parents=True)
    (pack / "pack.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "mypack",
                "description": "Custom for tests",
                "allow_list": ["alpha", "beta"],
            }
        ),
        encoding="utf-8",
    )
    (pack / "prompts.py").write_text(
        'MAIN_PROMPT = "m"\nRESEARCHER_PROMPT = "r"\n', encoding="utf-8"
    )
    (pack / "seeds" / "knowledge_base.json").write_text("[]", encoding="utf-8")
    (pack / "seeds" / "knowledge_graph.json").write_text("[]", encoding="utf-8")

    monkeypatch.setenv("DOMAINS_ROOT", str(tmp_path))
    monkeypatch.setenv("DOMAIN", "mypack")

    from langchain_core.tools import BaseTool

    from deep_agent import config
    from deep_agent import domain_pack as dp
    from deep_agent.tools import database_toolkit as dbt

    config.get_settings.cache_clear()
    dp.clear_active_pack_cache()
    dbt._database.cache_clear()
    dbt._toolkit.cache_clear()

    class _Inner(BaseTool):
        name: str = "q"
        description: str = "d"

        def _run(self, *args: Any, **kwargs: Any) -> str:
            return "ok"

    fake_toolkit = MagicMock()
    fake_toolkit.get_tools.return_value = [_Inner()]

    with patch(
        "deep_agent.tools.database_toolkit._toolkit", return_value=fake_toolkit
    ) as mock_tk:
        tools = dbt.get_data_tools(domain="mypack", db_name="deep_agent_mypack")

    # Toolkit was requested for the explicit db_name.
    mock_tk.assert_called_once_with("deep_agent_mypack")
    # Wrapper carries the pack's allow_list verbatim.
    assert len(tools) == 1
    assert tools[0].allow_list == {"alpha", "beta"}  # type: ignore[attr-defined]


def test_TC_40_INV_404_enforce_safety_unchanged() -> None:
    """INV-404: safety rules (destructive ops, underscore prefix, allow-list,
    implicit $limit) are untouched by spec 400. Spot-check all four."""
    from deep_agent.tools.database_toolkit import (
        DEFAULT_PIPELINE_LIMIT,
        QueryRefusedError,
        enforce_safety,
    )

    # Destructive op
    with pytest.raises(QueryRefusedError, match="destructive"):
        enforce_safety("orders", json.dumps([{"$out": "x"}]), {"orders"})
    # Underscore-prefixed collection
    with pytest.raises(QueryRefusedError, match="underscore"):
        enforce_safety("_hidden", json.dumps([{"$match": {}}]), set())
    # Non-allow-listed collection
    with pytest.raises(QueryRefusedError, match="disallowed"):
        enforce_safety("evil", json.dumps([{"$match": {}}]), {"orders"})
    # Implicit $limit injected
    out = enforce_safety("orders", json.dumps([{"$match": {}}]), {"orders"})
    stages = json.loads(out)
    assert stages[-1] == {"$limit": DEFAULT_PIPELINE_LIMIT}


def test_TC_40_427_safe_wrapper_catches_inner_tool_exception() -> None:
    """The safety wrapper must catch exceptions raised by the underlying
    MongoDB toolkit tool — a bare raise leaves the parent agent's ``tool_use``
    block without a ``tool_result`` and Bedrock rejects the next turn with
    ``tool_use ids were found without tool_result blocks``. Return a
    structured error string instead."""
    from langchain_core.tools import BaseTool

    from deep_agent.tools import database_toolkit as dbt

    class _Exploding(BaseTool):
        name: str = "t"
        description: str = "d"

        def _run(self, *args: Any, **kwargs: Any) -> str:
            raise RuntimeError("collection 'accounts' not found")

    wrapped = dbt._SafeToolWrapper(inner=_Exploding(), allow_list={"accounts"})

    out = wrapped._run(
        query=json.dumps([{"$match": {}}]), collection="accounts"
    )
    assert isinstance(out, str)
    assert out.startswith("QUERY ERROR")
    assert "RuntimeError" in out


def test_TC_40_INV_401_get_data_tools_no_args_uses_env() -> None:
    """INV-401: get_data_tools() with no args still resolves to env DOMAIN +
    Settings.mongodb_db (single-domain CLI path stays unchanged)."""
    from langchain_core.tools import BaseTool

    from deep_agent.tools import database_toolkit as dbt

    class _Inner(BaseTool):
        name: str = "q"
        description: str = "d"

        def _run(self, *args: Any, **kwargs: Any) -> str:
            return "ok"

    fake_toolkit = MagicMock()
    fake_toolkit.get_tools.return_value = [_Inner()]

    dbt._database.cache_clear()
    dbt._toolkit.cache_clear()
    with patch(
        "deep_agent.tools.database_toolkit._toolkit", return_value=fake_toolkit
    ) as mock_tk:
        tools = dbt.get_data_tools()

    # No-arg path does not pass an override: _toolkit should be called with None
    # (or no positional) so it binds to Settings.mongodb_db.
    args, _ = mock_tk.call_args
    assert args in ((), (None,))
    assert len(tools) == 1
