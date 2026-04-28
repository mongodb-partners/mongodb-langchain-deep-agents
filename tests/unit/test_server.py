"""Sub-phase 13: FastAPI app."""
from __future__ import annotations

from contextlib import ExitStack
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clear_settings() -> None:
    from deep_agent import config

    config.get_settings.cache_clear()


@pytest.fixture
def test_client():  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    fake_graph = MagicMock()

    async def _astream_events(*_args: Any, **_kwargs: Any):  # type: ignore[no-untyped-def]
        yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="Hello")}}
        yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content=" world")}}

    fake_graph.astream_events = _astream_events
    fake_graph.get_state.return_value = MagicMock(values={"todos": []})
    fake_history = MagicMock()

    with ExitStack() as stack:
        stack.enter_context(patch("deep_agent.server.app.build_graph", return_value=fake_graph))
        stack.enter_context(
            patch("deep_agent.server.app.build_chat_history", return_value=fake_history)
        )
        from deep_agent.server.app import create_app

        app = create_app()
        yield TestClient(app), fake_graph, fake_history


def test_TC_13_020_chat_sse_streams_tokens(test_client) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = test_client
    with client.stream(
        "POST", "/chat", json={"user_id": "u1", "thread_id": "t1", "message": "hi"}
    ) as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        body = b"".join(r.iter_bytes()).decode()
    assert "data:" in body
    assert "Hello" in body and "world" in body
    assert "[DONE]" in body


def test_TC_13_021_chat_requires_user_id(test_client) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = test_client
    r = client.post("/chat", json={"message": "hi"})
    assert r.status_code == 422


def test_TC_13_022_chat_default_thread_id(test_client) -> None:  # type: ignore[no-untyped-def]
    """thread_id defaults to '{user_id}:{domain}:default' when no thread_id
    is supplied (spec 400 scoped thread_id; see REQ-E-404)."""
    client, _, fake_history = test_client
    with ExitStack() as stack:
        bch = stack.enter_context(
            patch(
                "deep_agent.server.app.build_chat_history",
                return_value=fake_history,
            )
        )
        with client.stream("POST", "/chat", json={"user_id": "u1", "message": "hi"}) as r:
            b"".join(r.iter_bytes())
    # env default DOMAIN=reference; db_name resolves to deep_agent_test_reference.
    bch.assert_called_with("u1:reference:default", db_name="deep_agent_test_reference")


def test_TC_13_023_chat_swallow_history_errors() -> None:  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient
    from pymongo.errors import PyMongoError

    fake_graph = MagicMock()

    async def _stream(*_args: Any, **_kwargs: Any):  # type: ignore[no-untyped-def]
        yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="ok")}}

    fake_graph.astream_events = _stream
    fake_graph.get_state.return_value = MagicMock(values={"todos": []})
    fake_history = MagicMock()
    fake_history.add_user_message.side_effect = PyMongoError("down")
    fake_history.add_ai_message.side_effect = PyMongoError("down")

    with ExitStack() as stack:
        stack.enter_context(patch("deep_agent.server.app.build_graph", return_value=fake_graph))
        stack.enter_context(
            patch("deep_agent.server.app.build_chat_history", return_value=fake_history)
        )
        from deep_agent.server.app import create_app

        client = TestClient(create_app())
        with client.stream(
            "POST", "/chat", json={"user_id": "u1", "thread_id": "t1", "message": "hi"}
        ) as r:
            body = b"".join(r.iter_bytes()).decode()
    assert "ok" in body and "[DONE]" in body


def test_TC_13_024_chat_surfaces_stream_errors() -> None:  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    fake_graph = MagicMock()

    async def _boom(*_args: Any, **_kwargs: Any):  # type: ignore[no-untyped-def]
        if False:  # pragma: no cover
            yield {}
        raise RuntimeError("graph exploded")

    fake_graph.astream_events = _boom

    with ExitStack() as stack:
        stack.enter_context(patch("deep_agent.server.app.build_graph", return_value=fake_graph))
        stack.enter_context(
            patch("deep_agent.server.app.build_chat_history", return_value=MagicMock())
        )
        from deep_agent.server.app import create_app

        client = TestClient(create_app())
        with client.stream(
            "POST", "/chat", json={"user_id": "u1", "thread_id": "t1", "message": "hi"}
        ) as r:
            body = b"".join(r.iter_bytes()).decode()
    assert "event: error" in body
    assert "RuntimeError" in body


def test_TC_13_030_feedback_inserts(test_client) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = test_client
    with patch("deep_agent.server.app.get_db") as gdb:
        coll = MagicMock()
        db = MagicMock()
        db.__getitem__.return_value = coll
        gdb.return_value = db
        r = client.post(
            "/feedback",
            json={"run_id": "r1", "score": 1.0, "comment": "nice", "user_id": "u1"},
        )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    coll.insert_one.assert_called_once()


def test_TC_13_031_feedback_langsmith_mirror(
    monkeypatch: pytest.MonkeyPatch, test_client  # type: ignore[no-untyped-def]
) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    from deep_agent import config

    config.get_settings.cache_clear()

    client, _, _ = test_client
    with patch("deep_agent.server.app.get_db") as gdb, patch("langsmith.Client") as lc:
        coll = MagicMock()
        db = MagicMock()
        db.__getitem__.return_value = coll
        gdb.return_value = db
        lc.return_value.create_feedback = MagicMock()
        r = client.post(
            "/feedback",
            json={"run_id": "r1", "score": 0.5, "comment": "c", "user_id": "u1"},
        )
    assert r.status_code == 200
    lc.return_value.create_feedback.assert_called_once()


def test_TC_13_032_feedback_mirror_failure_swallowed(
    monkeypatch: pytest.MonkeyPatch, test_client  # type: ignore[no-untyped-def]
) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    from deep_agent import config

    config.get_settings.cache_clear()

    client, _, _ = test_client
    with patch("deep_agent.server.app.get_db") as gdb, patch("langsmith.Client") as lc:
        coll = MagicMock()
        db = MagicMock()
        db.__getitem__.return_value = coll
        gdb.return_value = db
        lc.side_effect = RuntimeError("ls down")
        r = client.post(
            "/feedback",
            json={"run_id": "r1", "score": 0.5, "comment": None, "user_id": "u1"},
        )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_TC_13_033_feedback_persistence_error(test_client) -> None:  # type: ignore[no-untyped-def]
    from pymongo.errors import PyMongoError

    client, _, _ = test_client
    with patch("deep_agent.server.app.get_db") as gdb:
        coll = MagicMock()
        coll.insert_one.side_effect = PyMongoError("down")
        db = MagicMock()
        db.__getitem__.return_value = coll
        gdb.return_value = db
        r = client.post(
            "/feedback",
            json={"run_id": "r1", "score": 0.0, "comment": None, "user_id": "u1"},
        )
    assert r.status_code == 500


def test_TC_13_040_health_reports_ok(test_client) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = test_client
    with patch("deep_agent.server.app.get_client") as gc:
        gc.return_value.admin.command.return_value = {"ok": 1}
        r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["mongo"] == "ok"


def test_TC_13_041_health_surfaces_pymongo_error(test_client) -> None:  # type: ignore[no-untyped-def]
    from pymongo.errors import PyMongoError

    client, _, _ = test_client
    with patch("deep_agent.server.app.get_client") as gc:
        gc.return_value.admin.command.side_effect = PyMongoError("unreachable")
        r = client.get("/health")
    assert r.status_code == 200
    assert "error" in r.json()["mongo"]
    assert "PyMongoError" in r.json()["mongo"]


# -------------------- Spec 400: /domains, /plans, X-Domain, CORS --------------------


def test_TC_40_403_get_domains_returns_pack_list(test_client) -> None:  # type: ignore[no-untyped-def]
    """REQ-E-403: GET /domains returns {domains: [{name, description}]}."""
    client, _, _ = test_client
    # Patch at the origin module so both /domains and resolve_domain see the
    # same fake list. The app module imports list_available at top level, so
    # we also patch there.
    with patch(
        "deep_agent.server.app.list_available",
        return_value=[
            {"name": "reference", "description": "Ref"},
            {"name": "pack_z", "description": "Z"},
        ],
    ):
        r = client.get("/domains")
    assert r.status_code == 200
    body = r.json()
    assert body["domains"][0]["name"] == "reference"
    assert body["domains"][1]["description"] == "Z"


def test_TC_40_400_chat_routes_by_x_domain_header(test_client) -> None:  # type: ignore[no-untyped-def]
    """REQ-E-400: X-Domain header resolves the active pack per request; the
    handler compiles (cached) a graph for that domain and injects
    domain + db_name into RunnableConfig.configurable."""
    client, fake_graph, _ = test_client
    captured_configs: list[Any] = []

    async def _capture_stream(_state: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        captured_configs.append(kwargs.get("config"))
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": MagicMock(content="hi")},
        }

    fake_graph.astream_events = _capture_stream
    with patch(
        "deep_agent.server.domain.list_available",
        return_value=[{"name": "pack_a", "description": "A"}],
    ), client.stream(
        "POST",
        "/chat",
        headers={"X-Domain": "pack_a"},
        json={"user_id": "alice", "message": "hi"},
    ) as r:
        b"".join(r.iter_bytes())

    assert captured_configs, "graph was not invoked"
    cfg = captured_configs[0]
    inner = cfg["configurable"]
    assert inner["domain"] == "pack_a"
    assert inner["db_name"] == "deep_agent_test_pack_a"
    assert inner["user_id"] == "alice"


def test_TC_40_INV_400_chat_without_header_uses_env_default(test_client) -> None:  # type: ignore[no-untyped-def]
    """INV-400 / REQ-E-401: no X-Domain → falls back to Settings.domain (env
    default), preserving single-domain behavior."""
    client, fake_graph, _ = test_client
    captured_configs: list[Any] = []

    async def _capture_stream(_state: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        captured_configs.append(kwargs.get("config"))
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": MagicMock(content="ok")},
        }

    fake_graph.astream_events = _capture_stream
    # Env default (unit tests set DOMAIN=reference in conftest) must be listed
    # so resolve_domain() accepts it.
    with patch(
        "deep_agent.server.domain.list_available",
        return_value=[{"name": "reference", "description": "Ref"}],
    ), client.stream(
        "POST", "/chat", json={"user_id": "alice", "message": "hi"}
    ) as r:
        b"".join(r.iter_bytes())

    assert captured_configs
    assert captured_configs[0]["configurable"]["domain"] == "reference"


def test_TC_40_402_chat_unknown_domain_returns_400(test_client) -> None:  # type: ignore[no-untyped-def]
    """REQ-E-402: X-Domain: <bogus> → HTTP 400 with list of valid domains."""
    client, _, _ = test_client
    with patch(
        "deep_agent.server.domain.list_available",
        return_value=[{"name": "reference", "description": "Ref"}],
    ):
        r = client.post(
            "/chat",
            headers={"X-Domain": "nosuchpack"},
            json={"user_id": "alice", "message": "hi"},
        )
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "nosuchpack" in detail
    assert "reference" in detail  # helpful: list the valid ones


def test_TC_40_EC_400_chat_path_traversal_rejected(test_client) -> None:  # type: ignore[no-untyped-def]
    """REQ-E-EC-400 / INV-410: X-Domain with '/', '\\', '..' → HTTP 400."""
    client, _, _ = test_client
    for bad in ["../etc", "foo/bar", "foo\\bar", ".."]:
        r = client.post(
            "/chat",
            headers={"X-Domain": bad},
            json={"user_id": "alice", "message": "hi"},
        )
        assert r.status_code == 400, f"expected 400 for X-Domain={bad!r}"


def test_TC_40_404_thread_id_embeds_domain(test_client) -> None:  # type: ignore[no-untyped-def]
    """REQ-E-404: thread_id passed to graph / chat_history is
    {user_id}:{domain}:{sub or default}."""
    client, fake_graph, fake_history = test_client
    captured_configs: list[Any] = []

    async def _capture_stream(_state: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        captured_configs.append(kwargs.get("config"))
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": MagicMock(content="ok")},
        }

    fake_graph.astream_events = _capture_stream

    with ExitStack() as stack:
        bch = stack.enter_context(
            patch(
                "deep_agent.server.app.build_chat_history",
                return_value=fake_history,
            )
        )
        stack.enter_context(
            patch(
                "deep_agent.server.domain.list_available",
                return_value=[{"name": "pack_a", "description": "A"}],
            )
        )
        with client.stream(
            "POST",
            "/chat",
            headers={"X-Domain": "pack_a"},
            json={"user_id": "alice", "thread_id": "sess1", "message": "hi"},
        ) as r:
            b"".join(r.iter_bytes())

    # chat_history was opened with the full scoped thread_id + per-domain db_name.
    bch.assert_called_with("alice:pack_a:sess1", db_name="deep_agent_test_pack_a")
    # Graph RunnableConfig also carries the scoped thread_id.
    assert captured_configs
    assert (
        captured_configs[0]["configurable"]["thread_id"] == "alice:pack_a:sess1"
    )


def test_TC_40_428_chat_sets_recursion_limit(test_client) -> None:  # type: ignore[no-untyped-def]
    """Multi-step planner prompts trip LangGraph's default recursion_limit=25.
    /chat must set recursion_limit = max(4 * Settings.max_hops, 50) on the
    RunnableConfig so plans like "pull X + pull Y + draft Z" complete."""
    client, fake_graph, _ = test_client
    captured_configs: list[Any] = []

    async def _capture(_state: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        captured_configs.append(kwargs.get("config"))
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": MagicMock(content="ok")},
        }

    fake_graph.astream_events = _capture
    with client.stream(
        "POST", "/chat", json={"user_id": "u1", "message": "hi"}
    ) as r:
        b"".join(r.iter_bytes())

    assert captured_configs
    rl = captured_configs[0].get("recursion_limit")
    # Default MAX_HOPS=20 → 4*20=80; floor at 50.
    assert isinstance(rl, int) and rl >= 50


def test_TC_40_EC_406_token_text_filters_structured_blocks() -> None:
    """REQ-E-EC-406: structured tool-use blocks must be filtered at the SSE
    boundary — only {"type": "text"} blocks are forwarded as token frames."""
    from deep_agent.server.app import _token_text

    # Bare string: passes through.
    assert _token_text("hello") == "hello"
    # List with text and tool_use: only text survives.
    blocks = [
        {"type": "text", "text": "Hi "},
        {"type": "tool_use", "input": {"x": 1}, "name": "recall"},
        {"type": "text", "text": "there"},
    ]
    assert _token_text(blocks) == "Hi there"
    # Unknown shapes collapse to empty string (never raises).
    assert _token_text(None) == ""
    assert _token_text({"type": "tool_use"}) == ""
    assert _token_text([{"type": "tool_use"}]) == ""


def test_TC_40_440_plans_endpoint_returns_snapshot() -> None:
    """REQ-E-440: GET /plans?user_id=&thread_id= returns
    {todos: [...], updated_at: <iso | null>}."""
    from fastapi.testclient import TestClient

    with ExitStack() as stack:
        stack.enter_context(
            patch("deep_agent.server.app.build_graph", return_value=MagicMock())
        )
        stack.enter_context(
            patch(
                "deep_agent.server.app.load_plan_snapshot",
                return_value={
                    "todos": [{"id": "1", "text": "x", "status": "pending"}],
                    "updated_at": "2026-04-27T10:00:00",
                },
            )
        )
        stack.enter_context(
            patch(
                "deep_agent.server.domain.list_available",
                return_value=[{"name": "reference", "description": "Ref"}],
            )
        )
        from deep_agent.server.app import create_app

        client = TestClient(create_app())
        r = client.get("/plans", params={"user_id": "alice", "thread_id": "alice:reference:default"})
    assert r.status_code == 200
    body = r.json()
    assert body["todos"][0]["text"] == "x"
    assert body["updated_at"] == "2026-04-27T10:00:00"


def test_TC_40_EC_405_plans_endpoint_empty_when_no_snapshot() -> None:
    """REQ-E-EC-405: missing snapshot → 200 with empty list (never 404)."""
    from fastapi.testclient import TestClient

    with ExitStack() as stack:
        stack.enter_context(
            patch("deep_agent.server.app.build_graph", return_value=MagicMock())
        )
        stack.enter_context(
            patch(
                "deep_agent.server.app.load_plan_snapshot",
                return_value={"todos": [], "updated_at": None},
            )
        )
        stack.enter_context(
            patch(
                "deep_agent.server.domain.list_available",
                return_value=[{"name": "reference", "description": "Ref"}],
            )
        )
        from deep_agent.server.app import create_app

        client = TestClient(create_app())
        r = client.get("/plans", params={"user_id": "ghost", "thread_id": "nothread"})
    assert r.status_code == 200
    assert r.json() == {"todos": [], "updated_at": None}


def test_TC_40_NF_402_cors_strict_by_default(test_client) -> None:  # type: ignore[no-untyped-def]
    """REQ-E-NF-402: CORS middleware responds to preflight with the configured
    origin (default http://localhost:3000) when ALLOW_INSECURE=false."""
    client, _, _ = test_client
    r = client.options(
        "/chat",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-domain,content-type",
        },
    )
    # Starlette's CORS preflight returns 200 on a match.
    assert r.status_code == 200
    assert (
        r.headers.get("access-control-allow-origin") == "http://localhost:3000"
    )


def test_TC_40_NF_402_cors_allow_all_when_insecure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REQ-E-NF-402: ALLOW_INSECURE=true → allow_origins=['*']."""
    monkeypatch.setenv("ALLOW_INSECURE", "true")
    monkeypatch.setenv("MONGODB_URI", "mongodb://dev:27017/")  # bypass TLS for this mode
    from deep_agent import config

    config.get_settings.cache_clear()

    from fastapi.testclient import TestClient

    with ExitStack() as stack:
        stack.enter_context(
            patch("deep_agent.server.app.build_graph", return_value=MagicMock())
        )
        from deep_agent.server.app import create_app

        client = TestClient(create_app())
    r = client.options(
        "/chat",
        headers={
            "Origin": "http://example.invalid:1234",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-domain",
        },
    )
    assert r.status_code == 200
    # CORSMiddleware echoes the origin when allow_origins=['*'] + credentials=True;
    # when credentials is False it emits '*' verbatim. Either is acceptable.
    origin = r.headers.get("access-control-allow-origin")
    assert origin in {"*", "http://example.invalid:1234"}


def test_TC_40_422_chat_does_not_wrap_stream_in_scoped_cache(test_client) -> None:  # type: ignore[no-untyped-def]
    """REQ-E-422 / D-404: /chat intentionally does NOT wrap the graph stream
    in ascoped_semantic_cache (LangChain global-cache swap serializes
    concurrent cross-domain requests). Assert the helper is never invoked
    from the handler."""
    client, fake_graph, _ = test_client

    async def _stream(*_a: Any, **_k: Any):  # type: ignore[no-untyped-def]
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": MagicMock(content="ok")},
        }

    fake_graph.astream_events = _stream
    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "deep_agent.server.domain.list_available",
                return_value=[{"name": "reference", "description": "Ref"}],
            )
        )
        ascoped = stack.enter_context(
            patch(
                "deep_agent.persistence.semantic_cache.ascoped_semantic_cache"
            )
        )
        with client.stream(
            "POST", "/chat", json={"user_id": "u1", "message": "hi"}
        ) as r:
            b"".join(r.iter_bytes())
    ascoped.assert_not_called()
