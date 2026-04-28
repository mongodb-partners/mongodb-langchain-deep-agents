"""Compile the deep-agent graph via :func:`deepagents.create_deep_agent`.

Invariants:
- Main agent binds KB + KG + fetch_and_cache + data-agent tools.
- A single `researcher` subagent owns the web-search tool.
- Checkpointer is :class:`MongoDBSaver`; cross-thread memory is :class:`MongoDBStore`.
- Semantic cache is installed at module import time for the CLI/worker path.

Per-domain (spec 400): ``build_graph(domain="<pack>")`` compiles a graph
whose persistence handles are bound to the ``<prefix>_<pack>`` database so
one backend process can serve every pack concurrently. The cache holds up
to 16 compiled graphs so the server path stays hot across packs.

The process-global semantic-cache install is deliberately skipped on
per-domain builds — the web `/chat` handler runs cacheless (see spec 400
decision D-404 for why).
"""
from __future__ import annotations

import contextlib
from functools import lru_cache
from typing import Any

from deepagents import create_deep_agent

from .agents.subagents import researcher_subagent
from .backends.mongo_backend import MongoVfsBackend
from .domain_pack import db_for, get_active_pack
from .middleware.patch_dangling import PatchDanglingToolCallsMiddleware
from .middleware.plan import PlanPersistenceMiddleware
from .models import get_llm
from .persistence.checkpointer import build_checkpointer
from .persistence.semantic_cache import install_semantic_cache
from .persistence.store import build_store
from .tools.database_toolkit import get_data_tools
from .tools.fetch_and_cache import fetch_and_cache
from .tools.knowledge_base_search import (
    knowledge_base_hybrid_search,
    knowledge_base_search,
)
from .tools.knowledge_graph_search import knowledge_graph_search
from .tools.memory import recall_memories, remember_fact


def _install_global_cache_once() -> None:
    """Install the semantic cache once per process. Silently skip if it fails."""
    with contextlib.suppress(Exception):
        install_semantic_cache()


def _main_agent_tools(
    domain: str | None = None, db_name: str | None = None
) -> list[Any]:
    return [
        knowledge_base_search,
        knowledge_base_hybrid_search,
        knowledge_graph_search,
        fetch_and_cache,
        remember_fact,
        recall_memories,
        *get_data_tools(domain=domain, db_name=db_name),
    ]


@lru_cache(maxsize=16)
def build_graph(domain: str | None = None) -> Any:
    """Build and compile the deep-agent graph with MongoDB persistence wired in.

    ``domain=None`` compiles the CLI / worker graph bound to
    ``Settings.mongodb_db`` (single-domain). An explicit ``domain`` compiles
    a graph bound to the per-domain DB (``<prefix>_<domain>``). The compiled
    graph is cached per domain so concurrent requests for the same pack share
    one instance.

    The process-global semantic-cache install is skipped when ``domain`` is
    set — the web server runs cacheless to avoid serializing concurrent
    cross-domain requests on LangChain's global-cache swap (spec 400 D-404).

    A single :class:`MongoVfsBackend` instance routes deepagents' built-in
    filesystem tools (``read_file``/``write_file``/``edit_file``/``ls``/
    ``glob``/``grep``) through our :class:`VirtualFilesystem` so artifacts
    land in MongoDB (GridFS or S3), not in-state. The backend resolves
    ``thread_id`` at each method call via ``langgraph.config.get_config()``,
    so one instance serves every turn with the correct scoping.
    """
    if domain is None:
        _install_global_cache_once()
    db_name = db_for(domain) if domain is not None else None
    return create_deep_agent(
        model=get_llm(),
        tools=_main_agent_tools(domain=domain, db_name=db_name),
        system_prompt=get_active_pack(domain).prompts.main,
        subagents=[researcher_subagent(domain=domain)],
        middleware=[PatchDanglingToolCallsMiddleware(), PlanPersistenceMiddleware()],
        checkpointer=build_checkpointer(db_name=db_name),
        store=build_store(db_name=db_name),
        backend=MongoVfsBackend(),
    )


def build_graph_uncheckpointed() -> Any:
    """Build the graph without persistence. Used by unit tests and linters."""
    return create_deep_agent(
        model=get_llm(),
        tools=_main_agent_tools(),
        system_prompt=get_active_pack().prompts.main,
        subagents=[researcher_subagent()],
    )
