"""Plan-persistence middleware.

Hooks into deepagents' ``after_model`` boundary. Every time the LLM emits a
``write_todos`` tool call, deepagents' :class:`TodoListMiddleware` updates
``state["todos"]`` — we intercept the resulting state, compare it against the
last persisted snapshot, and upsert to the MongoDB ``plans`` collection when
something changed.

Best-effort by construction: a :class:`PyMongoError` is logged and swallowed
so the planning loop never dies on plan-collection unavailability.
"""
from __future__ import annotations

import logging
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from pymongo.errors import PyMongoError

from ..persistence.plans import save_plan


def _configurable_from_runtime(runtime: Any) -> dict[str, Any]:
    """Return the active invocation's ``configurable`` dict.

    Deepagents' ``Runtime`` does not expose ``config`` directly; the active
    :class:`RunnableConfig` lives in a context variable that LangGraph sets
    before each node runs. We fall back to ``runtime.config`` for callers
    that construct a ``Runtime``-shaped mock (every unit test does this).
    """
    try:
        from langgraph.config import get_config

        active_cfg: Any = get_config()
        if isinstance(active_cfg, dict):
            configurable = active_cfg.get("configurable", {})
            if isinstance(configurable, dict) and configurable:
                return dict(configurable)
    except Exception:
        pass
    fallback: Any = getattr(runtime, "config", {}) or {}
    if isinstance(fallback, dict):
        inner = fallback.get("configurable", {})
        if isinstance(inner, dict):
            return dict(inner)
    return {}

log = logging.getLogger(__name__)


def _extract_todos(state: Any) -> list[dict[str, Any]]:
    if not isinstance(state, dict):
        return []
    raw = state.get("todos")
    if not isinstance(raw, list):
        return []
    return [t for t in raw if isinstance(t, dict)]


def _snapshot_key(todos: list[dict[str, Any]]) -> tuple[tuple[str, str, str], ...]:
    """Stable, hashable view of a todo list used to detect changes."""
    return tuple(
        (
            str(t.get("id", "")),
            str(t.get("content") or t.get("text") or ""),
            str(t.get("status", "pending")),
        )
        for t in todos
    )


class PlanPersistenceMiddleware(AgentMiddleware[Any, Any, Any]):
    """Upsert the deep-agent todo list on every model response.

    Tracks the last persisted snapshot per ``(user_id, thread_id)`` in
    process-local memory so a no-op model turn does not re-write the
    ``plans`` document.
    """

    def __init__(self) -> None:
        super().__init__()
        self.tools = []  # no tools added; this middleware just listens
        self._last_snapshot: dict[tuple[str, str], tuple[tuple[str, str, str], ...]] = {}

    def after_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        todos = _extract_todos(state)
        if not todos:
            return None

        configurable = _configurable_from_runtime(runtime)
        user_id = str(configurable.get("user_id") or "")
        thread_id = str(configurable.get("thread_id") or "")
        # Without db_name the save falls back to Settings.mongodb_db (the
        # base ``deep_agents`` DB), so /plans — which reads from
        # ``deep_agents_<pack>`` — would never see these todos until the
        # final server-side ``persist_plan_snapshot`` call at stream-done.
        # Route the write to the per-domain DB to match /plans' read path.
        db_name = configurable.get("db_name") or None
        if not user_id or not thread_id:
            return None

        snapshot = _snapshot_key(todos)
        key = (user_id, thread_id)
        if self._last_snapshot.get(key) == snapshot:
            return None

        # deepagents' TodoListMiddleware stores task text under ``content``;
        # our TodoItem schema uses ``text``. Map before saving.
        normalized = [
            {
                "id": str(t.get("id", "")),
                "text": str(t.get("text") or t.get("content") or ""),
                "status": t.get("status") if t.get("status") in ("pending", "in_progress", "completed") else "pending",
            }
            for t in todos
        ]

        try:
            save_plan(user_id, thread_id, normalized, db_name=db_name)
            self._last_snapshot[key] = snapshot
        except PyMongoError as exc:
            log.warning("PlanPersistenceMiddleware save failed: %s", exc)
        return None
