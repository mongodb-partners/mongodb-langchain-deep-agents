"""Sub-phase 09: fetch_and_cache tool."""
from __future__ import annotations

import hashlib
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    from deep_agent import config

    config.get_settings.cache_clear()


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError(
                "boom", request=None, response=None  # type: ignore[arg-type]
            )


class _FakeVS:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], list[dict[str, Any]]]] = []

    def add_texts(
        self, texts: list[str], metadatas: list[dict[str, Any]] | None = None
    ) -> list[str]:
        self.calls.append((list(texts), list(metadatas or [])))
        return ["id"] * len(texts)


class _FakeKBColl:
    """Stand-in for `knowledge_base.count_documents`-like lookup."""

    def __init__(self, existing_hashes: set[str]) -> None:
        self._existing = existing_hashes

    def count_documents(self, query: dict[str, Any], limit: int | None = None) -> int:
        h = query.get("metadata.content_hash")
        return 1 if h in self._existing else 0


class _StubVfs:
    def __init__(self) -> None:
        self.written: list[tuple[str, str, bytes]] = []

    def write_file(
        self, thread_id: str, path: str, data: bytes, *, content_type: str
    ) -> MagicMock:
        self.written.append((thread_id, path, data))
        m = MagicMock()
        m.locator = "loc-x"
        return m


def test_TC_09_020_fetch_and_cache_writes_vfs_and_kb() -> None:
    from deep_agent.tools import fetch_and_cache as fc

    vs = _FakeVS()
    vfs = _StubVfs()
    body = "a" * 2500  # Larger than one chunk so splitter produces > 1
    kb_coll = _FakeKBColl(existing_hashes=set())

    with patch("deep_agent.tools.fetch_and_cache.httpx") as httpx_mod, patch(
        "deep_agent.tools.fetch_and_cache.build_vector_store", return_value=vs
    ), patch("deep_agent.tools.fetch_and_cache.get_vfs", return_value=vfs), patch(
        "deep_agent.tools.fetch_and_cache.get_db"
    ) as gdb:
        client = MagicMock()
        client.get.return_value = _FakeResponse(body)
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=None)
        httpx_mod.Client.return_value = client
        httpx_mod.HTTPError = Exception  # placeholder for error propagation test
        gdb.return_value.__getitem__.return_value = kb_coll

        result = fc.fetch_and_cache.invoke(
            {"url": "https://example.com/x", "thread_id": "t1"}
        )

    assert result["cached"] is False
    assert result["chunks_added"] >= 2
    assert result["url"] == "https://example.com/x"
    # VFS write happened at web_cache/<hash[:12]>.html
    expected_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert len(vfs.written) == 1
    _, path, _ = vfs.written[0]
    assert path == f"web_cache/{expected_hash[:12]}.html"
    # KB add_texts metadata carries source url + content_hash
    assert len(vs.calls) == 1
    _, metadatas = vs.calls[0]
    assert metadatas and metadatas[0]["source"] == "https://example.com/x"
    assert metadatas[0]["content_hash"] == expected_hash


def test_TC_09_021_fetch_without_thread_id_skips_vfs() -> None:
    from deep_agent.tools import fetch_and_cache as fc

    vs = _FakeVS()
    vfs = _StubVfs()
    body = "short body"
    kb_coll = _FakeKBColl(existing_hashes=set())

    with patch("deep_agent.tools.fetch_and_cache.httpx") as httpx_mod, patch(
        "deep_agent.tools.fetch_and_cache.build_vector_store", return_value=vs
    ), patch("deep_agent.tools.fetch_and_cache.get_vfs", return_value=vfs), patch(
        "deep_agent.tools.fetch_and_cache.get_db"
    ) as gdb:
        client = MagicMock()
        client.get.return_value = _FakeResponse(body)
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=None)
        httpx_mod.Client.return_value = client
        httpx_mod.HTTPError = Exception
        gdb.return_value.__getitem__.return_value = kb_coll

        result = fc.fetch_and_cache.invoke({"url": "https://example.com/x"})

    assert result["cached"] is False
    assert result["chunks_added"] >= 1
    assert vfs.written == []
    assert len(vs.calls) == 1


def test_TC_09_030_fetch_hash_dedupe() -> None:
    from deep_agent.tools import fetch_and_cache as fc

    vs = _FakeVS()
    vfs = _StubVfs()
    body = "already-seen-body"
    expected_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    kb_coll = _FakeKBColl(existing_hashes={expected_hash})

    with patch("deep_agent.tools.fetch_and_cache.httpx") as httpx_mod, patch(
        "deep_agent.tools.fetch_and_cache.build_vector_store", return_value=vs
    ), patch("deep_agent.tools.fetch_and_cache.get_vfs", return_value=vfs), patch(
        "deep_agent.tools.fetch_and_cache.get_db"
    ) as gdb:
        client = MagicMock()
        client.get.return_value = _FakeResponse(body)
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=None)
        httpx_mod.Client.return_value = client
        httpx_mod.HTTPError = Exception
        gdb.return_value.__getitem__.return_value = kb_coll

        result = fc.fetch_and_cache.invoke(
            {"url": "https://example.com/seen", "thread_id": "t1"}
        )

    assert result == {
        "url": "https://example.com/seen",
        "cached": True,
        "chunks_added": 0,
    }
    # No ingest and no VFS write happened
    assert vs.calls == []
    assert vfs.written == []


def test_TC_09_040_fetch_returns_structured_error_on_http_failure() -> None:
    """HTTP / SSL / network errors must be returned as a structured ``error``
    field rather than raised. The deep-agent tool-calling contract requires a
    matching tool_result for every tool_use; an unhandled exception here
    would orphan the tool_use block and break strict validators like Bedrock."""
    import httpx

    from deep_agent.tools import fetch_and_cache as fc

    vs = _FakeVS()
    vfs = _StubVfs()
    kb_coll = _FakeKBColl(existing_hashes=set())

    with patch("deep_agent.tools.fetch_and_cache.build_vector_store", return_value=vs), patch(
        "deep_agent.tools.fetch_and_cache.get_vfs", return_value=vfs
    ), patch("deep_agent.tools.fetch_and_cache.get_db") as gdb, patch(
        "deep_agent.tools.fetch_and_cache.httpx"
    ) as httpx_mod:
        client = MagicMock()
        client.get.side_effect = httpx.ConnectError("nope")
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=None)
        httpx_mod.Client.return_value = client
        # Real httpx error hierarchy so the except clause actually matches
        httpx_mod.HTTPError = httpx.HTTPError
        gdb.return_value.__getitem__.return_value = kb_coll

        result = fc.fetch_and_cache.invoke({"url": "https://example.com/broken"})
        assert result["url"] == "https://example.com/broken"
        assert "error" in result
        assert "ConnectError" in result["error"]
        # Tool must not have ingested anything on failure
        assert vs.calls == []


# -------------------- Spec 400: db_name flows from RunnableConfig --------------------


def test_TC_40_413_fetch_reads_db_name_from_runtime_config() -> None:
    """REQ-E-413: fetch_and_cache routes both the existence-check (get_db) and
    the KB ingest (build_vector_store) through the db_name injected into
    RunnableConfig.configurable. Without a db_name the default (Settings) wins."""
    from deep_agent.tools import fetch_and_cache as fc

    vs = _FakeVS()
    kb_coll = _FakeKBColl(existing_hashes=set())
    captured_vs_db: list[str | None] = []
    captured_get_db_args: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def _fake_build_vs(db_name: str | None = None) -> _FakeVS:
        captured_vs_db.append(db_name)
        return vs

    class _FakeDb:
        def __getitem__(self, _key: str) -> _FakeKBColl:
            return kb_coll

    def _fake_get_db(db_name: str | None = None) -> _FakeDb:
        captured_get_db_args.append(((db_name,), {}))
        return _FakeDb()

    body = "x" * 1200
    with patch("deep_agent.tools.fetch_and_cache.httpx") as httpx_mod, patch(
        "deep_agent.tools.fetch_and_cache.build_vector_store",
        side_effect=_fake_build_vs,
    ), patch(
        "deep_agent.tools.fetch_and_cache.get_db", side_effect=_fake_get_db
    ):
        client = MagicMock()
        client.get.return_value = _FakeResponse(body)
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=None)
        httpx_mod.Client.return_value = client
        httpx_mod.HTTPError = Exception

        result = fc.fetch_and_cache.invoke(
            {"url": "https://example.com/scoped"},
            config={"configurable": {"db_name": "deep_agent_scoped"}},
        )

    assert result["cached"] is False
    # Both existence-check and ingest ran against the scoped DB.
    assert captured_vs_db == ["deep_agent_scoped"]
    assert captured_get_db_args == [(("deep_agent_scoped",), {})]
