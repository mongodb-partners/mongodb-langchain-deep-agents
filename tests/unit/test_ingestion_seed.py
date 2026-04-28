"""Sub-phase 14: seed loader tests."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SEED_ROOT = Path(__file__).resolve().parents[2] / "domains" / "reference" / "seeds"


@pytest.fixture(autouse=True)
def _clear_settings() -> None:
    from deep_agent import config

    config.get_settings.cache_clear()


def test_TC_14_010_seed_knowledge_base_writes_via_add_texts() -> None:
    from deep_agent.ingestion import seed as seeder

    fake_vs = MagicMock()
    with patch("deep_agent.ingestion.seed.build_vector_store", return_value=fake_vs):
        count = seeder.seed_knowledge_base()

    assert count == len(json.loads((SEED_ROOT / "knowledge_base.json").read_text()))
    args, kwargs = fake_vs.add_texts.call_args
    # Positional or keyword — tolerate both shapes
    texts = args[0] if args else kwargs.get("texts", [])
    assert len(texts) == count


def test_TC_14_011_seed_knowledge_graph_writes_documents() -> None:
    from langchain_core.documents import Document

    from deep_agent.ingestion import seed as seeder

    fake_gs = MagicMock()
    with patch("deep_agent.ingestion.seed.build_graph_store", return_value=fake_gs):
        count = seeder.seed_knowledge_graph()

    assert count == len(json.loads((SEED_ROOT / "knowledge_graph.json").read_text()))
    args, _ = fake_gs.add_documents.call_args
    docs = args[0]
    assert all(isinstance(d, Document) for d in docs)


def test_TC_14_012_seed_operational_inserts_per_file() -> None:
    import mongomock

    from deep_agent.ingestion import seed as seeder

    db = mongomock.MongoClient()["deep_agent_test"]
    with patch("deep_agent.ingestion.seed.get_db", return_value=db):
        counts = seeder.seed_operational_data()

    assert set(counts.keys()) == {"customers", "orders", "products"}
    for name, n in counts.items():
        assert db[name].count_documents({}) == n
        assert n > 0


def test_TC_14_013_seed_all_returns_composite_summary() -> None:
    import mongomock

    from deep_agent.ingestion import seed as seeder

    fake_vs = MagicMock()
    fake_gs = MagicMock()
    db = mongomock.MongoClient()["deep_agent_test"]
    with patch("deep_agent.ingestion.seed.build_vector_store", return_value=fake_vs), patch(
        "deep_agent.ingestion.seed.build_graph_store", return_value=fake_gs
    ), patch("deep_agent.ingestion.seed.get_db", return_value=db):
        summary = seeder.seed_all()

    assert set(summary.keys()) == {"knowledge_base", "knowledge_graph", "operational"}
    assert isinstance(summary["operational"], dict)
    assert summary["knowledge_base"] > 0
    assert summary["knowledge_graph"] > 0


def test_TC_14_020_seeds_are_domain_neutral() -> None:
    """Seed fixtures must stay industry-agnostic — the domain-swap contract
    documented in REQ-110/111."""
    import re

    forbidden = [r"\btelco\b", r"\bgep\b", r"\bfinance\b", r"\bhealthcare\b", r"\bphi\b"]
    offenders: list[tuple[str, str]] = []
    for path in SEED_ROOT.rglob("*.json"):
        text = path.read_text(encoding="utf-8").lower()
        for pat in forbidden:
            if re.search(pat, text):
                offenders.append((str(path.relative_to(SEED_ROOT.parents[3])), pat))
    assert not offenders, f"seed fixtures leaked industry terms: {offenders}"


def test_TC_14_014_missing_seed_file_is_noop() -> None:
    """A missing ``knowledge_base.json`` should return 0, not raise."""
    # Point at an empty directory by creating one
    import tempfile

    from deep_agent.ingestion import seed as seeder

    with tempfile.TemporaryDirectory() as tmp:
        assert seeder.seed_knowledge_base(seeds_dir=Path(tmp)) == 0
        assert seeder.seed_knowledge_graph(seeds_dir=Path(tmp)) == 0
        assert seeder.seed_operational_data(seeds_dir=Path(tmp)) == {}
