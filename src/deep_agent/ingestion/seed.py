"""Seed loader - idempotently populates the knowledge base, knowledge graph,
and operational data.

Reads JSON fixtures from the active domain pack's ``seeds/`` directory
(``domains/<name>/seeds/``) and writes to the configured Atlas collections.
Industry-swappable: change ``DOMAIN`` and seed a different pack without
touching persistence code.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from ..domain_pack import db_for, get_active_pack
from ..persistence.graph_store import build_graph_store
from ..persistence.mongo import get_db
from ..persistence.vector_store import build_vector_store

log = logging.getLogger(__name__)


def _default_seeds_dir() -> Path:
    return get_active_pack().seeds_dir


def _read_json(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON array")
    return data


def _resolve_db_name() -> str:
    """Return the domain-qualified DB name for the active pack."""
    domain = get_active_pack().name
    return db_for(domain)


def seed_knowledge_base(*, seeds_dir: Path | None = None) -> int:
    """Load ``knowledge_base.json`` and write each doc as an embedded chunk."""
    seeds_dir = seeds_dir or _default_seeds_dir()
    path = seeds_dir / "knowledge_base.json"
    if not path.exists():
        log.info("no knowledge_base.json at %s; skipping", path)
        return 0
    docs = _read_json(path)
    texts = [d["text"] for d in docs]
    metadatas = [d.get("metadata", {}) for d in docs]
    vs = build_vector_store(db_name=_resolve_db_name())
    vs.add_texts(texts, metadatas=metadatas)
    log.info("seeded %d knowledge_base chunks", len(texts))
    return len(texts)


def seed_knowledge_graph(*, seeds_dir: Path | None = None) -> int:
    """Load ``knowledge_graph.json`` and extract triples via :class:`MongoDBGraphStore`.

    Triple extraction runs the LLM; if the LLM output cannot be parsed as
    JSON for a given document, that document is skipped and seeding
    continues. This keeps the pipeline resilient to model-output drift.
    """
    seeds_dir = seeds_dir or _default_seeds_dir()
    path = seeds_dir / "knowledge_graph.json"
    if not path.exists():
        log.info("no knowledge_graph.json at %s; skipping", path)
        return 0
    rows = _read_json(path)
    documents = [Document(page_content=r["text"], metadata=r.get("metadata", {})) for r in rows]
    gs = build_graph_store(db_name=_resolve_db_name())
    ok = 0
    for doc in documents:
        try:
            gs.add_documents([doc])
            ok += 1
        except Exception as exc:
            log.warning("skipping knowledge_graph doc (%s): %s", doc.metadata, exc)
    log.info("seeded %d/%d knowledge_graph docs", ok, len(documents))
    return ok


def seed_operational_data(*, seeds_dir: Path | None = None) -> dict[str, int]:
    """Bulk-insert each ``operational/<name>.json`` into the collection ``<name>``."""
    seeds_dir = seeds_dir or _default_seeds_dir()
    op_dir = seeds_dir / "operational"
    if not op_dir.exists():
        log.info("no operational seeds at %s; skipping", op_dir)
        return {}
    counts: dict[str, int] = {}
    db = get_db(_resolve_db_name())
    for fp in sorted(op_dir.glob("*.json")):
        rows = _read_json(fp)
        if not rows:
            counts[fp.stem] = 0
            continue
        db[fp.stem].insert_many(rows)
        counts[fp.stem] = len(rows)
    log.info("seeded operational collections: %s", counts)
    return counts


def seed_all(*, seeds_dir: Path | None = None) -> dict[str, Any]:
    """Run the three seeders in order and return a summary."""
    return {
        "knowledge_base": seed_knowledge_base(seeds_dir=seeds_dir),
        "knowledge_graph": seed_knowledge_graph(seeds_dir=seeds_dir),
        "operational": seed_operational_data(seeds_dir=seeds_dir),
    }


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(seed_all())
