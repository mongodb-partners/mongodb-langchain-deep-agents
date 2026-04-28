"""GraphRAG traversal tool backed by :class:`MongoDBGraphStore`."""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pymongo.errors import OperationFailure

from ..agents._config import resolved_db_name
from ..persistence.graph_store import build_graph_store

log = logging.getLogger(__name__)


@lru_cache(maxsize=16)
def _graph_store(db_name: str | None = None) -> Any:
    """Cache one graph-store handle per distinct ``db_name``.

    ``db_name=None`` resolves to ``Settings.mongodb_db`` inside
    ``build_graph_store`` (single-domain / CLI). The web server passes a
    per-request db_name.
    """
    return build_graph_store(db_name=db_name)


@tool
def knowledge_graph_search(
    query: str, config: RunnableConfig | None = None
) -> str:
    """Traverse the knowledge graph to answer an entity-relation question.

    Returns a natural-language answer composed by the underlying
    ``MongoDBGraphStore.chat_response`` (which retrieves related entities,
    builds context, and asks the LLM).
    """
    db_name = resolved_db_name(config)
    try:
        result = _graph_store(db_name).chat_response(query)
    except OperationFailure as exc:
        # langchain-mongodb's graphrag extract_entity_names can return a
        # non-list shape, producing `$in needs an array` at the traversal
        # aggregation. KG is best-effort: surface a sentinel so the agent
        # can still answer from parametric knowledge.
        log.warning("knowledge_graph_search traversal failed: %s", exc)
        return "No matching entities found in the knowledge graph for this query."
    return str(getattr(result, "content", result))
