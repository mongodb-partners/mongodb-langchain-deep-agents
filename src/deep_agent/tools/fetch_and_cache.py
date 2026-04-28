"""Fetch a URL, cache the raw page in the VFS, and ingest chunks into the KB.

Dedupe via SHA-256 of the response body: when the same body has already been
ingested (``metadata.content_hash`` in ``knowledge_base``), the tool returns
``{cached: True, chunks_added: 0}`` without re-embedding.

Per-domain routing (spec 400): both the existence-check and the KB write run
against the DB resolved from ``RunnableConfig.configurable.db_name``. When no
config is supplied the tool falls back to ``Settings.mongodb_db`` — the
single-domain CLI path is unchanged.
"""
from __future__ import annotations

import contextlib
import hashlib
import logging
from typing import Any

import httpx
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..agents._config import resolved_db_name
from ..config import get_settings
from ..persistence.mongo import get_db
from ..persistence.vector_store import build_vector_store
from ..vfs import get_vfs

log = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30.0
_USER_AGENT = "deep-agent/0.1 (+https://www.mongodb.com/)"


def _already_ingested(content_hash: str, db_name: str | None) -> bool:
    s = get_settings()
    kb = get_db(db_name)[s.knowledge_base_collection]
    return bool(kb.count_documents({"metadata.content_hash": content_hash}, limit=1))


@tool
def fetch_and_cache(
    url: str,
    thread_id: str | None = None,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Fetch ``url``, store the raw page in the VFS, and ingest chunks into the KB.

    When ``thread_id`` is provided the raw body is cached under
    ``web_cache/<hash[:12]>.html`` in the VFS. If the content hash is already
    present in ``knowledge_base``, the call is a no-op and returns
    ``{cached: True, chunks_added: 0}``.

    HTTP/SSL/network errors return ``{"url": url, "error": "<message>"}``
    rather than raising. Tool-result blocks must always land next to their
    tool-use blocks for Bedrock's strict validator, so any unhandled exception
    here leaves the turn in a state the LLM cannot recover from.
    """
    db_name = resolved_db_name(config)
    try:
        with httpx.Client(
            timeout=_DEFAULT_TIMEOUT, headers={"User-Agent": _USER_AGENT}
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
            body = resp.text
    except (httpx.HTTPError, OSError) as exc:
        log.warning("fetch_and_cache HTTP/network failure for %s: %s", url, exc)
        return {"url": url, "error": f"{type(exc).__name__}: {exc}"[:400]}

    content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()

    if _already_ingested(content_hash, db_name):
        return {"url": url, "cached": True, "chunks_added": 0}

    if thread_id:
        # Best-effort VFS cache — ingestion must not fail because the VFS is misbehaving.
        with contextlib.suppress(Exception):
            vfs = get_vfs(db_name)
            vfs.write_file(
                thread_id,
                f"web_cache/{content_hash[:12]}.html",
                body.encode("utf-8"),
                content_type="text/html",
            )

    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    chunks = splitter.split_text(body)
    metadatas = [{"source": url, "content_hash": content_hash} for _ in chunks]
    try:
        vector_store = build_vector_store(db_name=db_name)
        vector_store.add_texts(chunks, metadatas=metadatas)
    except Exception as exc:
        log.warning("fetch_and_cache KB ingest failed for %s: %s", url, exc)
        return {"url": url, "error": f"KB ingest failed: {type(exc).__name__}"}

    log.info("fetch_and_cache ingested %d chunks from %s", len(chunks), url)
    return {"url": url, "cached": False, "chunks_added": len(chunks)}
