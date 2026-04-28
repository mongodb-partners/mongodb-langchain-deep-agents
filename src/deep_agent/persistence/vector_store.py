"""Knowledge-base vector store (Atlas Vector Search)."""
from __future__ import annotations

from langchain_mongodb import MongoDBAtlasVectorSearch

from ..config import get_settings
from ..models import get_embeddings
from .mongo import get_db


def build_vector_store(db_name: str | None = None) -> MongoDBAtlasVectorSearch:
    """Return a :class:`MongoDBAtlasVectorSearch` bound to the knowledge-base collection.

    ``db_name=None`` uses ``Settings.mongodb_db`` (CLI / worker). The web
    server passes a per-domain DB so each pack has its own KB.
    """
    s = get_settings()
    collection = get_db(db_name)[s.knowledge_base_collection]
    return MongoDBAtlasVectorSearch(
        collection=collection,
        embedding=get_embeddings(),
        index_name=s.knowledge_base_vector_index,
        text_key="text",
        embedding_key="embedding",
        relevance_score_fn="cosine",
        dimensions=s.voyage_dimensions,
        auto_create_index=False,  # ensure_indexes() handles DDL explicitly
    )
