"""Idempotent creation of Atlas Search / Vector Search / compound indexes.

Called once at application startup so adopters don't have to click through the
Atlas UI. Each index creation is wrapped in a try/except on
``OperationFailure`` so re-runs are safe.
"""
from __future__ import annotations

import contextlib
import logging
from typing import Any

from pymongo.errors import OperationFailure

from ..config import get_settings
from ..domain_pack import db_for, get_active_pack
from .mongo import get_db

log = logging.getLogger(__name__)


def _ensure_collection(db: Any, name: str) -> Any:
    """Atlas requires a namespace to exist before vector/search indexes can be
    created on it. ``listCollections`` + ``create_collection`` is cheap and
    idempotent (we swallow ``NamespaceExists``).
    """
    if name not in db.list_collection_names():
        try:
            db.create_collection(name)
        except OperationFailure as exc:
            if getattr(exc, "code", None) != 48:  # NamespaceExists
                raise
    return db[name]


def _search_index_needs_update(
    collection: Any, name: str, definition: dict[str, Any]
) -> bool:
    """Return True if an existing search index lacks filter fields declared in
    ``definition``. Atlas's ``create_search_index`` is a no-op when one with
    the same name exists, so we need explicit drift detection to heal stale
    shapes (e.g. a vector index missing a newly-required filter path).
    """
    want_filters = {
        f["path"]
        for f in definition.get("fields", [])
        if f.get("type") == "filter" and isinstance(f.get("path"), str)
    }
    if not want_filters:
        return False
    try:
        existing = list(collection.list_search_indexes(name))
    except OperationFailure:
        return False
    for ix in existing:
        latest = ix.get("latestDefinition") or ix.get("definition") or {}
        have_filters = {
            f.get("path")
            for f in latest.get("fields", [])
            if f.get("type") == "filter"
        }
        if not want_filters.issubset(have_filters):
            return True
    return False


def _safe_create_search_index(
    collection: Any,
    definition: dict[str, Any],
    name: str,
    type: str = "vectorSearch",
) -> None:
    """Idempotently create an Atlas Search / Vector Search index. If the
    index already exists but is missing required filter paths, drop and
    recreate it (Atlas has no in-place filter-add API)."""
    model = {"name": name, "type": type, "definition": definition}

    if _search_index_needs_update(collection, name, definition):
        log.warning(
            "search index %s on %s is missing required filter fields; "
            "dropping and recreating",
            name,
            collection.name,
        )
        with contextlib.suppress(OperationFailure):
            collection.drop_search_index(name)

    try:
        collection.create_search_index(model=model)
        log.info("created Atlas Search index %s on %s", name, collection.name)
    except OperationFailure as exc:
        if "already exists" in str(exc).lower() or getattr(exc, "code", None) in (68, 86):
            log.info("index %s already exists on %s - skipping", name, collection.name)
            return
        raise


def ensure_indexes(db_name: str | None = None) -> None:
    """Create every Atlas index the runtime needs. Idempotent.

    ``db_name`` targets a specific database. When omitted, resolves via
    the active domain pack (CLI / single-domain path).
    """
    s = get_settings()
    if db_name is None:
        domain = get_active_pack().name
        db_name = db_for(domain)
    db = get_db(db_name)

    # Knowledge base — vector + text
    kb = _ensure_collection(db, s.knowledge_base_collection)
    _safe_create_search_index(
        kb,
        {
            "mappings": {"dynamic": False},
            "fields": [
                {
                    "type": "vector",
                    "path": "embedding",
                    "numDimensions": s.voyage_dimensions,
                    "similarity": "cosine",
                },
                {"type": "filter", "path": "metadata.source"},
            ],
        },
        name=s.knowledge_base_vector_index,
    )
    _safe_create_search_index(
        kb,
        {"mappings": {"dynamic": True}},
        name=s.knowledge_base_search_index,
        type="search",
    )

    # Semantic cache — vector + ``llm_string`` filter scopes hits per model tuple
    cache = _ensure_collection(db, s.llm_cache_collection)
    _safe_create_search_index(
        cache,
        {
            "fields": [
                {
                    "type": "vector",
                    "path": "embedding",
                    "numDimensions": s.voyage_dimensions,
                    "similarity": "cosine",
                },
                {"type": "filter", "path": "llm_string"},
            ]
        },
        name=s.llm_cache_vector_index,
    )

    # Long-term memory. MongoDBStore.search runs an aggregation that filters
    # by ``namespace_prefix`` before/around the $vectorSearch stage, so Atlas
    # requires that field to be declared as a filter. Without it, every
    # search() raises "Path 'namespace_prefix' needs to be indexed as filter".
    mem = _ensure_collection(db, s.long_term_memory_collection)
    _safe_create_search_index(
        mem,
        {
            "fields": [
                {
                    "type": "vector",
                    "path": "embedding",
                    "numDimensions": s.voyage_dimensions,
                    "similarity": "cosine",
                },
                {"type": "filter", "path": "namespace_prefix"},
            ]
        },
        name=s.long_term_memory_vector_index,
    )

    # Chat history — ``MongoDBChatMessageHistory(create_index=True)`` owns the
    # ``(SessionId, 1)`` index and picks its own name. Creating it here under a
    # different name raises ``IndexOptionsConflict`` (code 85) at first write.

    # Knowledge graph — MongoDBGraphStore lazy-creates the collection on first
    # add_documents(), but if seed never succeeds (e.g. first boot before
    # seeding) then knowledge_graph_search tools fail with "collection does
    # not exist". Provision upfront and add a type index to make traversal
    # queries (filter by entity type) cheap.
    kg = _ensure_collection(db, s.knowledge_graph_collection)
    with contextlib.suppress(OperationFailure):
        kg.create_index([("type", 1)], name="kg_type_idx")

    # Stream events — 30-day TTL
    events = _ensure_collection(db, s.stream_events_collection)
    with contextlib.suppress(OperationFailure):
        events.create_index(
            [("ts", 1)],
            expireAfterSeconds=60 * 60 * 24 * 30,
            name="ts_ttl_idx",
        )

    # Feedback — index by thread_id for lookup when investigating a turn
    feedback = _ensure_collection(db, s.feedback_collection)
    with contextlib.suppress(OperationFailure):
        feedback.create_index(
            [("thread_id", 1), ("ts", -1)],
            name="feedback_thread_ts_idx",
        )

    # VFS metadata — unique per (thread_id, path) so duplicate writes upsert
    vfs = db[s.vfs_files_collection]
    with contextlib.suppress(OperationFailure):
        vfs.create_index(
            [("thread_id", 1), ("path", 1)],
            unique=True,
            name="vfs_thread_path_unique",
        )

    # Plans — unique per (user_id, thread_id) so resume loads one document
    plans = db[s.plans_collection]
    with contextlib.suppress(OperationFailure):
        plans.create_index(
            [("user_id", 1), ("thread_id", 1)],
            unique=True,
            name="plans_user_thread_unique",
        )
