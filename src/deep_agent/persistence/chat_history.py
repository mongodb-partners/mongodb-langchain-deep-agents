"""MongoDB-backed conversation history per session."""
from __future__ import annotations

from langchain_mongodb import MongoDBChatMessageHistory

from ..config import get_settings


def build_chat_history(
    session_id: str, db_name: str | None = None
) -> MongoDBChatMessageHistory:
    """Return a history handle for ``session_id`` (== LangGraph thread_id).

    ``db_name`` defaults to ``Settings.mongodb_db`` (CLI / worker). The web
    server passes a per-domain DB name so chat-history rows for different
    packs don't co-mingle.
    """
    s = get_settings()
    return MongoDBChatMessageHistory(
        connection_string=s.mongodb_uri.get_secret_value(),
        session_id=session_id,
        database_name=db_name if db_name is not None else s.mongodb_db,
        collection_name=s.chat_history_collection,
        create_index=True,
    )
