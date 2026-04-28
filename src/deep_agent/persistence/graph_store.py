"""GraphRAG knowledge graph (``MongoDBGraphStore``)."""
from __future__ import annotations

from langchain_mongodb.graphrag.graph import MongoDBGraphStore

from ..config import get_settings
from ..models import get_llm
from .mongo import get_db


def build_graph_store(db_name: str | None = None) -> MongoDBGraphStore:
    """Return a :class:`MongoDBGraphStore` using the shared LLM for entity extraction.

    ``db_name=None`` uses ``Settings.mongodb_db`` (CLI / worker). The web
    server passes a per-domain DB so each pack has its own KG.
    """
    s = get_settings()
    collection = get_db(db_name)[s.knowledge_graph_collection]
    return MongoDBGraphStore(
        collection=collection,
        entity_extraction_model=get_llm(),
    )
