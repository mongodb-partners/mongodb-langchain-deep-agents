"""Subagent factories for the deep-agent graph."""
from __future__ import annotations

from typing import Any

from deepagents import SubAgent

from ..domain_pack import get_active_pack
from ..middleware.patch_dangling import PatchDanglingToolCallsMiddleware
from ..tools.fetch_and_cache import fetch_and_cache
from ..tools.knowledge_base_search import (
    knowledge_base_hybrid_search,
    knowledge_base_search,
)
from ..tools.knowledge_graph_search import knowledge_graph_search
from ..tools.web_search import web_search


def researcher_subagent(domain: str | None = None) -> SubAgent:
    """Return the `researcher` subagent specification.

    Bound tools match the ``RESEARCHER_PROMPT`` instructions: KB retrieval
    (vector + hybrid + graph) and web tooling (search + fetch_and_cache).

    ``domain=None`` uses the env-default pack (CLI / worker). Under the
    multi-domain web server the graph factory passes the active pack name so
    the system prompt matches the pack the request targets. Tools themselves
    read ``domain``/``db_name`` from ``RunnableConfig`` at call time (spec
    400), so the subagent doesn't need to re-bind tool handles per domain.
    """
    tools: list[Any] = [
        web_search,
        fetch_and_cache,
        knowledge_base_search,
        knowledge_base_hybrid_search,
        knowledge_graph_search,
    ]
    return SubAgent(
        name="researcher",
        description=(
            "Deep-dive a sub-question using the knowledge base and the web; "
            "ingest new findings back into the knowledge base."
        ),
        system_prompt=get_active_pack(domain).prompts.researcher,
        tools=tools,
        middleware=[PatchDanglingToolCallsMiddleware()],
    )
