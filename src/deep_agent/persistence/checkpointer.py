"""LangGraph checkpointer backed by MongoDB Atlas.

Uses :class:`langgraph.checkpoint.mongodb.MongoDBSaver` — no custom MongoDB code.
"""
from __future__ import annotations

from langgraph.checkpoint.mongodb import MongoDBSaver

from ..config import get_settings
from .mongo import get_client


def build_checkpointer(db_name: str | None = None) -> MongoDBSaver:
    """Return a :class:`MongoDBSaver` configured against the shared client.

    Persists every super-step to ``checkpoints`` and pending writes to
    ``checkpoint_writes`` in ``db_name`` (defaults to ``Settings.mongodb_db``
    for the CLI / worker path; the web server passes a per-domain DB name).
    """
    s = get_settings()
    return MongoDBSaver(
        client=get_client(),
        db_name=db_name if db_name is not None else s.mongodb_db,
        checkpoint_collection_name=s.checkpoints_collection,
        writes_collection_name=s.checkpoint_writes_collection,
    )
