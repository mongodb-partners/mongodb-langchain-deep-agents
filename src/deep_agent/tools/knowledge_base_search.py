"""Knowledge-base search tools backed by Atlas Vector Search + Atlas $search.

Two retrieval primitives are exposed so the researcher subagent can pick the
right one for the query:

* :func:`knowledge_base_search` — pure vector similarity (``$vectorSearch``),
  optionally narrowed by a ``source`` metadata filter.
* :func:`knowledge_base_hybrid_search` — Reciprocal Rank Fusion of vector +
  lexical ``$search`` via :class:`MongoDBAtlasHybridSearchRetriever`.

Both tools post-process results through :class:`VoyageAIRerank` (rerank-2.5)
before returning to the agent.

Per-domain routing (spec 400): the tools read ``db_name`` from the
``RunnableConfig`` that LangGraph injects into each tool call and resolve
their vector store against that DB. Outside a graph runtime the tools fall
back to ``Settings.mongodb_db`` — the single-domain CLI path is unchanged.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from langchain_core.documents import Document
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from ..agents._config import resolved_db_name
from ..models import get_reranker
from ..persistence.vector_store import build_vector_store

log = logging.getLogger(__name__)


@lru_cache(maxsize=16)
def _vector_store(db_name: str | None = None) -> Any:
    """Cache one vector-store handle per distinct ``db_name``.

    ``db_name=None`` resolves to ``Settings.mongodb_db`` inside
    ``build_vector_store`` (single-domain / CLI path). The web server passes
    a per-request db_name so concurrent cross-domain requests don't share a
    handle.
    """
    return build_vector_store(db_name=db_name)


@lru_cache(maxsize=16)
def build_hybrid_retriever(db_name: str | None = None) -> Any:
    """Build (and cache) the RRF-hybrid retriever per ``db_name``."""
    from langchain_mongodb.retrievers import MongoDBAtlasHybridSearchRetriever

    from ..config import get_settings

    s = get_settings()
    return MongoDBAtlasHybridSearchRetriever(
        vectorstore=_vector_store(db_name),
        search_index_name=s.knowledge_base_search_index,
        top_k=4,
    )


def _hybrid_retriever(db_name: str | None = None) -> Any:
    """Indirection so tests can monkeypatch the retriever without hitting the cache."""
    return build_hybrid_retriever(db_name)


def _rerank(query: str, docs: list[Document], top_n: int) -> list[Document]:
    """Apply Voyage rerank-2.5 to ``docs`` and return the top ``top_n``.

    Rerank failures must not fail the turn — fall back to the original order.
    """
    if not docs:
        return docs
    try:
        reranker = get_reranker()
        reranked = reranker.compress_documents(docs, query)
        return list(reranked)[:top_n]
    except Exception:
        return docs[:top_n]


def _hits_to_string(hits: list[dict[str, Any]]) -> str:
    """Serialize KB hits as a JSON string.

    LangChain's Bedrock adapter (``_format_anthropic_messages``) silently
    drops ``ToolMessage`` content that is an empty list, which orphans the
    preceding ``tool_use`` block and makes Bedrock reject the next turn.
    Returning a string guarantees the result survives that conversion.
    """
    import json
    if not hits:
        return "No results."
    return json.dumps(hits, ensure_ascii=False)


@tool
def knowledge_base_search(
    query: str,
    k: int = 4,
    source: str | None = None,
    config: RunnableConfig | None = None,
) -> str:
    """Search the knowledge base via Atlas ``$vectorSearch``, then rerank with Voyage.

    When ``source`` is provided it is forwarded as a ``pre_filter`` on
    ``metadata.source`` so Atlas narrows candidates during HNSW traversal.
    Returns a JSON-serialized string of ``{text, metadata}`` hits.
    """
    fetch_k = max(k * 3, k)
    kwargs: dict[str, Any] = {"k": fetch_k}
    if source:
        kwargs["pre_filter"] = {"metadata.source": {"$eq": source}}
    db_name = resolved_db_name(config)
    # KB retrieval is best-effort. A raised exception here would orphan the
    # parent agent's ``tool_use`` block — Bedrock's strict validator then
    # rejects the NEXT turn with "tool_use ids were found without tool_result
    # blocks immediately after". Missing index, empty collection, transient
    # Atlas errors all have to degrade gracefully instead.
    try:
        docs: list[Document] = _vector_store(db_name).similarity_search(query, **kwargs)
    except Exception as exc:
        log.warning("knowledge_base_search failed (db=%s): %s", db_name, exc)
        return _hits_to_string([])
    top = _rerank(query, docs, top_n=k)
    return _hits_to_string([{"text": d.page_content, "metadata": d.metadata} for d in top])


@tool
def knowledge_base_hybrid_search(
    query: str, config: RunnableConfig | None = None
) -> str:
    """Search the knowledge base via RRF hybrid, then rerank with Voyage.

    Prefer this tool when the query contains distinctive keywords or proper
    nouns where lexical match materially improves recall. Returns a
    JSON-serialized string of ``{text, metadata}`` hits.
    """
    db_name = resolved_db_name(config)
    # Same best-effort contract as ``knowledge_base_search`` above — any raise
    # here corrupts the tool_use/tool_result pairing on the next Bedrock turn.
    try:
        docs: list[Document] = _hybrid_retriever(db_name).invoke(query)
    except Exception as exc:
        log.warning("knowledge_base_hybrid_search failed (db=%s): %s", db_name, exc)
        return _hits_to_string([])
    top = _rerank(query, docs, top_n=4)
    return _hits_to_string([{"text": d.page_content, "metadata": d.metadata} for d in top])
