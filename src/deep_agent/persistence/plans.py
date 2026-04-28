"""Deep-agent plan persistence.

Upserts and loads deep-agent todo lists to the ``plans`` collection keyed by
``(user_id, thread_id)``. The compound unique index is created by
:func:`ensure_indexes`.

Per-domain routing (spec 400): every public function accepts an optional
``db_name`` so the web ``/chat`` and ``/plans`` handlers can route writes
and reads to the pack-specific database (``<prefix>_<pack>``). When
``db_name`` is omitted the single-domain CLI default (``Settings.mongodb_db``)
is used, matching prior behavior.

This module only knows how to read and write the plan document; the
graph-side :class:`PlanPersistenceMiddleware` is what invokes :func:`save_plan`
on every ``after_model`` hook.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..config import get_settings
from .mongo import get_db


class TodoItem(BaseModel):
    id: str
    text: str
    status: Literal["pending", "in_progress", "completed"] = "pending"


class PlanDoc(BaseModel):
    user_id: str
    thread_id: str
    todos: list[TodoItem] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


def _collection(db_name: str | None = None) -> Any:
    s = get_settings()
    return get_db(db_name)[s.plans_collection]


def _coerce_todos(items: Sequence[TodoItem | dict[str, Any]]) -> list[TodoItem]:
    out: list[TodoItem] = []
    for item in items:
        if isinstance(item, TodoItem):
            out.append(item)
        else:
            out.append(TodoItem(**item))
    return out


def save_plan(
    user_id: str,
    thread_id: str,
    todos: Sequence[TodoItem | dict[str, Any]],
    db_name: str | None = None,
) -> PlanDoc:
    """Upsert the plan for ``(user_id, thread_id)``.

    ``created_at`` is preserved across upserts; ``updated_at`` advances.
    Raw dicts are accepted for ergonomic callback integration and coerced
    into :class:`TodoItem`. ``db_name`` routes the write to a per-domain DB
    (web server); omit it on CLI / worker paths.
    """
    coll = _collection(db_name)
    # BSON stores datetimes without tz info and at millisecond precision; normalize
    # both writes and reads to the same naive-UTC, millisecond-precision shape so
    # round-trips compare equal.
    raw = datetime.now(UTC).replace(tzinfo=None)
    now = raw.replace(microsecond=(raw.microsecond // 1000) * 1000)
    coerced = _coerce_todos(todos)

    existing = coll.find_one({"user_id": user_id, "thread_id": thread_id})
    created_at = existing["created_at"] if existing else now
    doc = PlanDoc(
        user_id=user_id,
        thread_id=thread_id,
        todos=coerced,
        created_at=created_at,
        updated_at=now,
    )
    coll.update_one(
        {"user_id": user_id, "thread_id": thread_id},
        {"$set": doc.model_dump(mode="python")},
        upsert=True,
    )
    return doc


def load_plan(
    user_id: str, thread_id: str, db_name: str | None = None
) -> PlanDoc | None:
    """Return the plan for ``(user_id, thread_id)`` or ``None``."""
    doc = _collection(db_name).find_one({"user_id": user_id, "thread_id": thread_id})
    if doc is None:
        return None
    return PlanDoc(
        user_id=doc["user_id"],
        thread_id=doc["thread_id"],
        todos=[TodoItem(**t) for t in doc.get("todos", [])],
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


def delete_plan(
    user_id: str, thread_id: str, db_name: str | None = None
) -> bool:
    """Drop the plan. Returns True on hit."""
    res = _collection(db_name).delete_one(
        {"user_id": user_id, "thread_id": thread_id}
    )
    return bool(res.deleted_count)


def load_plan_snapshot(
    user_id: str, thread_id: str, db_name: str | None = None
) -> dict[str, Any]:
    """Return ``{"todos": [...], "updated_at": <iso | None>}`` for the UI.

    Shape is tuned for the ``/plans`` endpoint the deep-agent web UI polls
    after every SSE ``done`` frame. A missing snapshot returns
    ``{"todos": [], "updated_at": None}`` — never ``None``; never 404 —
    because the UI polls blindly and must render a consistent shape.

    Each todo is serialized as ``{"id", "text", "status"}`` (matching
    :class:`TodoItem.model_dump`) so the UI can render status glyphs.
    """
    doc = load_plan(user_id, thread_id, db_name=db_name)
    if doc is None:
        return {"todos": [], "updated_at": None}
    return {
        "todos": [t.model_dump() for t in doc.todos],
        "updated_at": doc.updated_at.isoformat(),
    }


def persist_plan_snapshot(
    state: Any,
    *,
    user_id: str,
    thread_id: str,
    db_name: str | None = None,
) -> PlanDoc | None:
    """Extract todos from deep-agent state and upsert to the plans collection.

    Deep-agent state (0.5.x) exposes ``state["todos"]`` where each item has
    ``id``, ``content`` (the task text), and ``status``. We map
    ``content -> text`` to match :class:`TodoItem`.

    Best-effort: a :class:`pymongo.errors.PyMongoError` here must not break
    the user turn. Other exception types propagate so real bugs are not masked.
    """
    import logging

    from pymongo.errors import PyMongoError

    log = logging.getLogger(__name__)
    try:
        raw_todos = state.get("todos", []) if isinstance(state, dict) else []
    except AttributeError:
        return None

    items: list[TodoItem] = []
    for raw in raw_todos:
        if not isinstance(raw, dict):
            continue
        text = raw.get("text") or raw.get("content") or ""
        status_raw = raw.get("status", "pending")
        if status_raw not in ("pending", "in_progress", "completed"):
            status_raw = "pending"
        items.append(
            TodoItem(
                id=str(raw.get("id") or ""),
                text=str(text),
                status=status_raw,
            )
        )

    try:
        return save_plan(user_id, thread_id, items, db_name=db_name)
    except PyMongoError as exc:
        log.warning("persist_plan_snapshot failed: %s", exc)
        return None
