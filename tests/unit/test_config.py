"""Sub-phase 02: Settings (TLS enforcement, redaction, env loading)."""
from __future__ import annotations

import pytest


def test_TC_02_010_settings_loads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONGODB_DB", "custom_db")
    monkeypatch.setenv("VFS_BACKEND", "s3")
    monkeypatch.setenv("VFS_S3_BUCKET", "test-bucket")
    from deep_agent.config import get_settings

    get_settings.cache_clear()
    s = get_settings()
    assert s.mongodb_db == "custom_db"
    # unspecified optional fields fall through to their defaults
    assert s.llm_provider == "bedrock"
    assert s.voyage_dimensions == 1024
    assert s.vfs_backend == "s3"


def test_TC_02_020_tls_enforcement(monkeypatch: pytest.MonkeyPatch) -> None:
    from deep_agent.config import Settings, get_settings

    get_settings.cache_clear()
    # plain URI without TLS markers → rejected
    monkeypatch.setenv("MONGODB_URI", "mongodb://fake:27017/")
    monkeypatch.setenv("ALLOW_INSECURE", "false")
    with pytest.raises(ValueError, match="TLS"):
        Settings()

    # +srv → allowed
    monkeypatch.setenv("MONGODB_URI", "mongodb+srv://user:pass@cluster.mongodb.net/")
    Settings()

    # tls=true in plain URI → allowed
    monkeypatch.setenv("MONGODB_URI", "mongodb://fake:27017/?tls=true")
    Settings()

    # allow_insecure bypass
    monkeypatch.setenv("MONGODB_URI", "mongodb://fake:27017/")
    monkeypatch.setenv("ALLOW_INSECURE", "true")
    Settings()


def test_TC_02_030_secret_redaction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "MONGODB_URI", "mongodb+srv://super:secret-password@cluster.mongodb.net/"
    )
    monkeypatch.setenv("VOYAGE_API_KEY", "pa-super-secret-voyage-key")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-super-secret-langsmith")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-super-secret")

    from deep_agent.config import Settings, get_settings

    get_settings.cache_clear()
    s = Settings()
    rep = repr(s)
    assert "secret-password" not in rep
    assert "pa-super-secret-voyage-key" not in rep
    assert "ls-super-secret-langsmith" not in rep
    assert "tvly-super-secret" not in rep
    assert str(s) == rep
    assert "[redacted]" in rep


def test_TC_02_031_s3_config_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VFS_BACKEND", "s3")
    monkeypatch.delenv("VFS_S3_BUCKET", raising=False)
    from deep_agent.config import Settings, get_settings

    get_settings.cache_clear()
    with pytest.raises(ValueError, match="VFS_S3_BUCKET"):
        Settings()

    monkeypatch.setenv("VFS_S3_BUCKET", "bucket-xyz")
    s = Settings()
    assert s.vfs_backend == "s3"
    assert s.vfs_s3_bucket == "bucket-xyz"


def test_TC_02_080_get_settings_cached() -> None:
    from deep_agent.config import get_settings

    get_settings.cache_clear()
    a = get_settings()
    b = get_settings()
    assert a is b
