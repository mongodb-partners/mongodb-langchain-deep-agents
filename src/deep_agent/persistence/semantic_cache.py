"""Install ``MongoDBAtlasSemanticCache`` as the process-global LangChain LLM cache.

Two flavors are exposed:

* :func:`install_semantic_cache` — one-shot, process-global install. Used by
  CLI / worker paths that resolve a single domain at startup.
* :func:`scoped_semantic_cache` / :func:`ascoped_semantic_cache` — context
  managers that install a cache bound to a given DB name for the duration of
  a block and restore the prior cache on exit. Present for CLI / test / future
  use; the FastAPI ``/chat`` handler deliberately does **not** wrap its
  stream in these (see spec 400 decision D-404: the asyncio.Lock serializes
  all concurrent cross-domain requests, which measured ~5x wall-time
  regression in the sibling repo).

Caveat: ``set_llm_cache`` mutates a *process-global* in LangChain. The scoped
helpers serialize their install/restore region with sync/async locks so
concurrent uses don't stomp each other's restore order.
"""
from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

from langchain_core.globals import get_llm_cache, set_llm_cache
from langchain_mongodb import MongoDBAtlasSemanticCache

from ..config import get_settings
from ..models import get_embeddings

_installed = False

# Protects the global-cache swap region. Sync and async paths use distinct
# primitives; both are module-level so every scoped install is serialized.
_sync_lock = threading.Lock()
_async_lock: asyncio.Lock | None = None


def _build_cache(db_name: str) -> MongoDBAtlasSemanticCache:
    s = get_settings()
    return MongoDBAtlasSemanticCache(
        connection_string=s.mongodb_uri.get_secret_value(),
        embedding=get_embeddings(),
        collection_name=s.llm_cache_collection,
        database_name=db_name,
        index_name=s.llm_cache_vector_index,
        score_threshold=s.semantic_cache_threshold,
    )


def install_semantic_cache() -> MongoDBAtlasSemanticCache:
    """Install the semantic cache globally. Idempotent per process.

    Uses ``Settings.mongodb_db`` as the DB. CLI / worker paths call this once
    at startup; the web server does NOT call this (nor the scoped variants)
    on the ``/chat`` path — see module docstring.
    """
    global _installed
    cache = _build_cache(get_settings().mongodb_db)
    set_llm_cache(cache)
    _installed = True
    return cache


@contextmanager
def scoped_semantic_cache(db_name: str) -> Iterator[MongoDBAtlasSemanticCache]:
    """Install a semantic cache bound to ``db_name``; restore prior cache on exit.

    Synchronous variant — held across a single block. Callers that need the
    async graph event loop must use :func:`ascoped_semantic_cache`.
    """
    with _sync_lock:
        prior: Any = get_llm_cache()
        cache = _build_cache(db_name)
        set_llm_cache(cache)
        try:
            yield cache
        finally:
            set_llm_cache(prior)


def _get_async_lock() -> asyncio.Lock:
    global _async_lock
    if _async_lock is None:
        _async_lock = asyncio.Lock()
    return _async_lock


@asynccontextmanager
async def ascoped_semantic_cache(
    db_name: str,
) -> AsyncIterator[MongoDBAtlasSemanticCache]:
    """Async variant of :func:`scoped_semantic_cache`.

    The lock is held for the duration of the block. This serializes concurrent
    cross-domain uses at the LLM-call boundary — correct but not scalable.
    See module docstring for why ``/chat`` does not use this.
    """
    lock = _get_async_lock()
    async with lock:
        prior: Any = get_llm_cache()
        cache = _build_cache(db_name)
        set_llm_cache(cache)
        try:
            yield cache
        finally:
            set_llm_cache(prior)


def is_installed() -> bool:
    return _installed
