"""Shared model layer: LLM, embeddings, reranker.

Every agent / tool / retriever / cache obtains its LLM or embedder through the
factories here so swapping providers is a single-module change.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_voyageai import VoyageAIEmbeddings, VoyageAIRerank

from .config import get_settings


@lru_cache(maxsize=1)
def get_llm() -> BaseChatModel:
    """Return the configured chat model.

    Uses :func:`langchain.chat_models.init_chat_model` so the provider can be
    flipped via ``LLM_PROVIDER`` / ``LLM_MODEL`` env vars without touching
    agent code.
    """
    s = get_settings()
    kwargs: dict[str, Any] = {
        "model": s.llm_model,
        "model_provider": s.llm_provider,
        # Claude models silently truncate in-progress ``tool_use`` JSON when
        # they hit the output-token ceiling, leaving the pydantic validator to
        # reject the partial args (e.g. ``write_file`` arriving with
        # ``file_path`` but no ``content``). Bedrock's per-call default is
        # well below the model's capability, so we pin this near the model
        # limit. Opus 4.7 supports up to 128k output; 32k is a safe ceiling
        # that accommodates long VFS writes without burning unnecessary tokens.
        "max_tokens": s.max_tokens,
    }
    # Claude Opus 4.7+ deprecates `temperature`. Older models still accept it.
    if "opus-4-7" not in s.llm_model:
        kwargs["temperature"] = 0
    if s.llm_provider == "bedrock":
        kwargs["region_name"] = s.aws_region
    llm: BaseChatModel = init_chat_model(**kwargs)
    return llm


class AsymmetricVoyageEmbeddings(Embeddings):
    """Embeddings that route ingestion and query to different Voyage models.

    ``voyage-4`` and ``voyage-4-lite`` share a common embedding space, so a
    document indexed with the high-capacity model is correctly retrievable by
    a query embedded with the latency-optimized lite model.
    """

    def __init__(
        self,
        document_model: VoyageAIEmbeddings,
        query_model: VoyageAIEmbeddings,
    ) -> None:
        self._document_model = document_model
        self._query_model = query_model

    @property
    def document_model(self) -> VoyageAIEmbeddings:
        return self._document_model

    @property
    def query_model(self) -> VoyageAIEmbeddings:
        return self._query_model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._document_model.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._query_model.embed_query(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._document_model.aembed_documents(texts)

    async def aembed_query(self, text: str) -> list[float]:
        return await self._query_model.aembed_query(text)


@lru_cache(maxsize=1)
def get_embeddings() -> Embeddings:
    """Return an asymmetric Voyage embedder.

    Documents embedded with ``VOYAGE_DOCUMENT_MODEL`` (default ``voyage-4``);
    queries embedded with ``VOYAGE_QUERY_MODEL`` (default ``voyage-4-lite``).
    ``VOYAGE_BASE_URL`` (if set) routes both embedders through a gateway.
    """
    s = get_settings()
    common: dict[str, Any] = {"voyage_api_key": s.voyage_api_key}
    if s.voyage_base_url:
        common["base_url"] = s.voyage_base_url
    doc_embedder = VoyageAIEmbeddings(model=s.voyage_document_model, **common)
    query_embedder = VoyageAIEmbeddings(model=s.voyage_query_model, **common)
    return AsymmetricVoyageEmbeddings(doc_embedder, query_embedder)


@lru_cache(maxsize=1)
def get_reranker() -> VoyageAIRerank:
    """Return the configured Voyage AI reranker."""
    s = get_settings()
    kwargs: dict[str, Any] = {
        "model": s.voyage_rerank_model,
        "voyage_api_key": s.voyage_api_key,
    }
    if s.voyage_base_url:
        kwargs["base_url"] = s.voyage_base_url
    return VoyageAIRerank(**kwargs)
