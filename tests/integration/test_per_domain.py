"""Per-domain seed + search integration tests (spec 200, REQ-E-240..243).

For each shipped pack, this test:
1. Swaps DOMAIN to that pack
2. Ensures indexes on a unique test database
3. Runs seed_all() to load the pack's KB, graph, and operational collections
4. Searches the KB for a pack-specific anchor phrase
5. Asserts at least one hit and that the anchor appears in the result

Gated on ATLAS_URI + VOYAGE_API_KEY. A clean no-op when either is unset.

Note: the KB Atlas Vector Search index is eventually consistent. The test
polls for up to 60 seconds for the index to surface the new documents
before asserting. On a brand-new test DB the first seed also needs the
index created via ensure_indexes() - this typically takes 30-60 seconds on
Atlas.
"""
from __future__ import annotations

import os
import time
import uuid
from collections.abc import Iterator
from typing import Any

import pytest

pytestmark = pytest.mark.integration

# Each pack has: (query_phrase, expected_tokens_any_of).
# The query drives vector retrieval; the tokens are the fuzzy check on the
# top result. We require >= 1 result and at least one matching token.
_PACK_ANCHORS: dict[str, tuple[str, tuple[str, ...]]] = {
    "reference": ("Atlas Vector Search", ("vector search", "$vectorsearch")),
    "healthcare": ("vancomycin treatment", ("vancomycin", "fidaxomicin", "cdi")),
    "finance": ("Regulation E dispute window", ("regulation e", "dispute", "1005")),
    "telco": ("MTTR target SLA breach", ("mttr", "sla", "tier")),
    "retail": ("return policy 30 days", ("return", "30 days", "delivery")),
}


@pytest.fixture
def voyage_key() -> str:
    key = os.environ.get("VOYAGE_API_KEY")
    if not key:
        pytest.skip("VOYAGE_API_KEY not set; skipping per-domain search test")
    return key


@pytest.fixture
def per_pack_db(atlas_uri: str, voyage_key: str) -> Iterator[str]:
    """Allocate a unique test DB name that the test will seed and clean up."""
    db_name = f"deep_agent_pack_test_{uuid.uuid4().hex[:8]}"
    os.environ["MONGODB_URI"] = atlas_uri
    os.environ["MONGODB_DB"] = db_name
    yield db_name
    # Teardown - drop the test database even on failure.
    from pymongo import MongoClient

    client: MongoClient[Any] = MongoClient(atlas_uri)
    try:
        client.drop_database(db_name)
    finally:
        client.close()


def _clear_caches() -> None:
    from deep_agent import config as _cfg
    from deep_agent import domain_pack as _dp
    from deep_agent.persistence.mongo import reset_for_tests
    from deep_agent.tools import knowledge_base_search as kbs
    from deep_agent.tools.database_toolkit import clear_data_tools_cache

    _cfg.get_settings.cache_clear()
    _dp.clear_active_pack_cache()
    clear_data_tools_cache()
    reset_for_tests()
    # knowledge_base_search caches its vector store + hybrid retriever bound
    # to the MONGODB_DB at first-call time; without clearing, a second pack's
    # search hits the previous pack's DB and returns nothing.
    kbs._vector_store.cache_clear()
    kbs.build_hybrid_retriever.cache_clear()


def _wait_for_hit(
    search_fn: Any, query: str, tokens: tuple[str, ...], timeout_s: int = 120
) -> list[Any]:
    """Poll a search function until results contain any of the expected tokens."""
    deadline = time.time() + timeout_s
    last_results: list[Any] = []
    while time.time() < deadline:
        last_results = search_fn(query) or []
        blob = "\n".join(str(r) for r in last_results).lower()
        if blob and any(tok.lower() in blob for tok in tokens):
            return last_results
        time.sleep(5)
    return last_results


@pytest.mark.parametrize("pack", list(_PACK_ANCHORS.keys()))
def test_TC_INT_200_per_domain_seed_and_search(
    pack: str, atlas_uri: str, per_pack_db: str
) -> None:
    """REQ-E-240/241/242/243 verified end-to-end: each pack seeds and searches
    correctly against live Atlas."""
    os.environ["DOMAIN"] = pack
    _clear_caches()

    from deep_agent.ingestion.seed import seed_all
    from deep_agent.persistence.indexes import ensure_indexes
    from deep_agent.tools.knowledge_base_search import knowledge_base_search

    ensure_indexes()
    summary = seed_all()
    assert summary["knowledge_base"] > 0, f"{pack}: seed_all returned zero KB docs"

    query, tokens = _PACK_ANCHORS[pack]
    results = _wait_for_hit(
        lambda q: knowledge_base_search.invoke({"query": q}), query, tokens
    )

    assert results, f"{pack}: knowledge_base_search returned no results for {query!r}"
    blob = "\n".join(str(r) for r in results).lower()
    assert any(tok.lower() in blob for tok in tokens), (
        f"{pack}: no hit contained any of {tokens!r}. Query={query!r}. Results: {results!r}"
    )
