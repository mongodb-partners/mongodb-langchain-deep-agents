"""Unit-test-only fixtures.

Autouse env fixture pins every setting this project reads so unit tests are
hermetic regardless of the developer's local ``.env``. We also point
pydantic-settings at a non-existent env file so developers who keep real
credentials in the repo's ``.env`` do not leak them into test settings.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Disable .env loading for unit tests. Some developers keep a real `.env`
    # in the repo root; without this, `BaseSettings` would fall back to those
    # credentials whenever a test uses `monkeypatch.delenv` to simulate
    # "secret not set" and the real key is still in the file.
    monkeypatch.setenv("DEEP_AGENT_ENV_FILE", "/dev/null")
    monkeypatch.setenv("MONGODB_URI", "mongodb://fake:27017/?tls=true")
    monkeypatch.setenv("MONGODB_DB", "deep_agent_test")
    monkeypatch.setenv("VOYAGE_API_KEY", "pa-test-voyage")
    monkeypatch.setenv("LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("LLM_MODEL", "global.anthropic.claude-sonnet-4-6")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("VOYAGE_DOCUMENT_MODEL", "voyage-4")
    monkeypatch.setenv("VOYAGE_QUERY_MODEL", "voyage-4-lite")
    monkeypatch.setenv("VOYAGE_DIMENSIONS", "1024")
    monkeypatch.setenv("VFS_BACKEND", "gridfs")
    monkeypatch.setenv("ALLOW_INSECURE", "false")
    monkeypatch.setenv("DOMAIN", "reference")
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("DATA_AGENT_MONGODB_URI", raising=False)
    monkeypatch.delenv("VOYAGE_BASE_URL", raising=False)
    monkeypatch.delenv("DOMAINS_ROOT", raising=False)


@pytest.fixture(autouse=True)
def _clear_caches(_set_required_env: None) -> None:
    """Clear settings + pack + graph caches between tests so DOMAIN/DOMAINS_ROOT
    swaps take effect. Depends on ``_set_required_env`` so the env-file override
    (DEEP_AGENT_ENV_FILE=/dev/null) is in place before ``config`` is imported."""
    from deep_agent import config as _cfg
    from deep_agent import domain_pack as _dp
    from deep_agent import graph as _graph

    _cfg.get_settings.cache_clear()
    _dp.clear_active_pack_cache()
    _graph.build_graph.cache_clear()
    yield
    _cfg.get_settings.cache_clear()
    _dp.clear_active_pack_cache()
    _graph.build_graph.cache_clear()
