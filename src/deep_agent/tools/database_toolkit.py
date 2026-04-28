"""NL → MQL via :class:`MongoDBDatabaseToolkit` with a defense-in-depth safety wrapper.

Protections layered on top of the native toolkit:

1. **Collection allow-list**: only whitelisted collections are queryable.
2. **Underscore block**: any collection whose name begins with ``_`` is refused.
3. **Destructive-op refusal**: pipelines containing ``$out`` / ``$merge`` /
   ``$function`` / ``$where`` / ``$accumulator`` server-side JS, or
   insert/update/delete keywords, are refused.
4. **Implicit ``$limit``**: pipelines without an explicit ``$limit`` stage are
   capped at 1000 documents.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from langchain_core.tools import BaseTool
from langchain_mongodb.agent_toolkit import MongoDBDatabase, MongoDBDatabaseToolkit

from ..config import get_settings
from ..domain_pack import get_active_pack
from ..models import get_llm

DESTRUCTIVE_PATTERNS = re.compile(
    r"\$(out|merge|function|where|accumulator)\b", re.IGNORECASE
)
KEYWORD_PATTERNS = re.compile(
    r"\b(drop|deleteMany|deleteOne|updateMany|updateOne|insertMany|insertOne)\b"
)

DEFAULT_PIPELINE_LIMIT = 1000

# Match ``db.<collection>.<op>(...)`` or ``<collection>.<op>(...)`` query forms.
_DB_COLLECTION_PATTERN = re.compile(
    r"(?:db\.)?([A-Za-z_][A-Za-z0-9_]*)\.(?:find|aggregate|count|countDocuments|distinct)\b"
)


def _extract_collection(pipeline_text: str) -> str:
    """Best-effort parse of the target collection from a query string."""
    if not isinstance(pipeline_text, str):
        return ""
    m = _DB_COLLECTION_PATTERN.search(pipeline_text)
    if m:
        return m.group(1)
    # JSON-style ``{"collection": "foo", ...}``
    try:
        obj = json.loads(pipeline_text)
    except (json.JSONDecodeError, ValueError):
        return ""
    if isinstance(obj, dict):
        c = obj.get("collection") or obj.get("coll")
        if isinstance(c, str):
            return c
    return ""


class QueryRefusedError(RuntimeError):
    """Raised when a tool-generated query violates safety policy."""


def _looks_destructive(pipeline_text: str) -> str | None:
    if DESTRUCTIVE_PATTERNS.search(pipeline_text):
        return "destructive aggregation stage"
    if KEYWORD_PATTERNS.search(pipeline_text):
        return "destructive keyword"
    return None


def _has_explicit_limit(pipeline_text: str) -> bool:
    return "$limit" in pipeline_text


def enforce_safety(collection: str, pipeline_text: str, allow_list: set[str]) -> str:
    """Inspect a pipeline request and return a safe version, or raise."""
    if collection.startswith("_"):
        raise QueryRefusedError(
            f"refusing query on internal collection '{collection}' (underscore-prefixed)"
        )
    if allow_list and collection not in allow_list:
        raise QueryRefusedError(
            f"refusing query on disallowed collection '{collection}'; "
            f"allow-list: {sorted(allow_list)}"
        )
    reason = _looks_destructive(pipeline_text)
    if reason:
        raise QueryRefusedError(f"refusing destructive pipeline ({reason})")
    if not _has_explicit_limit(pipeline_text):
        try:
            stages = json.loads(pipeline_text)
            if isinstance(stages, list):
                stages.append({"$limit": DEFAULT_PIPELINE_LIMIT})
                return str(json.dumps(stages))
        except json.JSONDecodeError:
            pass
    return pipeline_text


@lru_cache(maxsize=16)
def _database(db_name: str | None = None) -> MongoDBDatabase:
    """Resolve a MongoDBDatabase handle for ``db_name``.

    ``db_name=None`` uses ``Settings.mongodb_db`` (single-domain CLI path).
    The multi-domain web server passes a per-request db_name; each distinct
    key gets its own cached handle (up to ``maxsize=16``).
    """
    s = get_settings()
    uri_secret = s.data_agent_mongodb_uri or s.mongodb_uri
    name = db_name if db_name is not None else s.mongodb_db
    return MongoDBDatabase.from_connection_string(
        connection_string=uri_secret.get_secret_value(),
        database=name,
    )


@lru_cache(maxsize=16)
def _toolkit(db_name: str | None = None) -> MongoDBDatabaseToolkit:
    return MongoDBDatabaseToolkit(db=_database(db_name), llm=get_llm())


def get_data_tools(
    domain: str | None = None, db_name: str | None = None
) -> list[BaseTool]:
    """Return the MongoDBDatabaseToolkit tools wrapped with the safety layer.

    ``domain=None`` resolves the active pack via env (``Settings.domain``).
    ``db_name=None`` binds the inner toolkit to ``Settings.mongodb_db``.
    The multi-domain web server passes both per request so allow-list and DB
    handle are both correctly scoped.
    """
    tools = list(_toolkit(db_name).get_tools())
    allow_list = set(get_active_pack(domain).allow_list)
    return [_SafeToolWrapper(inner=t, allow_list=allow_list) for t in tools]


def clear_data_tools_cache() -> None:
    """Clear the toolkit + database caches. Used by tests that swap packs."""
    _database.cache_clear()
    _toolkit.cache_clear()


class _SafeToolWrapper(BaseTool):
    """Wraps a toolkit tool; inspects every call for unsafe queries."""

    inner: Any
    allow_list: set[str]
    name: str = "mongo_tool"
    description: str = "MongoDB tool (safety-wrapped)"

    def __init__(self, inner: Any, allow_list: set[str]) -> None:
        kwargs: dict[str, Any] = dict(
            inner=inner,
            allow_list=allow_list,
            name=inner.name,
            description=inner.description + " (safety-wrapped)",
        )
        # Forward the inner tool's args_schema so the LLM sees the real
        # parameter names (e.g. ``query``, ``collection_names``) instead of
        # the ``*args, **kwargs`` placeholders our wrapper declares.
        inner_schema = getattr(inner, "args_schema", None)
        if inner_schema is not None:
            kwargs["args_schema"] = inner_schema
        super().__init__(**kwargs)

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        pipeline_text = (
            kwargs.get("query")
            or kwargs.get("pipeline")
            or (args[0] if args else "")
        )
        # Only ``mongodb_query`` / ``mongodb_query_checker`` hit live data; the
        # ``mongodb_schema`` and ``mongodb_list_collections`` tools take
        # non-query kwargs (``collection_names``, ``tool_input``) and must not
        # be funneled through ``enforce_safety``.
        if self.inner.name not in {"mongodb_query", "mongodb_query_checker"}:
            pipeline_text = ""
        collection = kwargs.get("collection") or _extract_collection(pipeline_text)
        if isinstance(pipeline_text, str) and pipeline_text:
            try:
                pipeline_text = enforce_safety(collection, pipeline_text, self.allow_list)
            except QueryRefusedError as exc:
                return f"QUERY REFUSED: {exc}"
            if kwargs.get("query") is not None:
                kwargs["query"] = pipeline_text
            elif kwargs.get("pipeline") is not None:
                kwargs["pipeline"] = pipeline_text
            elif args:
                args = (pipeline_text, *args[1:])
        # Best-effort contract: a raised exception here would orphan the
        # parent agent's ``tool_use`` block and Bedrock would reject the next
        # turn. Return a structured error string instead so the agent can
        # adjust and retry or move on.
        try:
            return self.inner._run(*args, **kwargs)
        except Exception as exc:
            return f"QUERY ERROR: {type(exc).__name__}: {exc}"[:400]

    async def _arun(self, *args: Any, **kwargs: Any) -> Any:
        return self._run(*args, **kwargs)
