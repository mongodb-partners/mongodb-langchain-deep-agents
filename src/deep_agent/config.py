"""Application settings loaded from environment variables and .env.

Single source of truth for secrets + tunables. Redacted in ``repr`` so
accidental logging does not leak credentials.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ``DEEP_AGENT_ENV_FILE`` lets tests (and tightly-controlled environments) opt
# out of implicit ``.env`` loading. Default is the conventional ``.env``.
_ENV_FILE = os.environ.get("DEEP_AGENT_ENV_FILE", ".env")


def _default_domains_root() -> Path:
    # <repo_root>/domains -- src/deep_agent/config.py -> parents[2] is repo root.
    return Path(__file__).resolve().parents[2] / "domains"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- MongoDB ---
    mongodb_uri: SecretStr = Field(..., alias="MONGODB_URI")
    mongodb_db: str = Field("deep_agent", alias="MONGODB_DB")
    data_agent_mongodb_uri: SecretStr | None = Field(None, alias="DATA_AGENT_MONGODB_URI")

    # --- LLM ---
    llm_provider: str = Field("bedrock", alias="LLM_PROVIDER")
    # Default chosen for Bedrock subagent compatibility: Sonnet 4.5 has a known
    # interaction with deepagents subagents where the `task` tool's
    # tool_use / tool_result pairing trips Bedrock's strict validator. Sonnet
    # 4.6 handles that cleanly.
    llm_model: str = Field(
        "global.anthropic.claude-sonnet-4-6",
        alias="LLM_MODEL",
    )
    aws_region: str = Field("us-east-1", alias="AWS_DEFAULT_REGION")

    # --- Embeddings (Voyage AI) ---
    voyage_api_key: SecretStr = Field(..., alias="VOYAGE_API_KEY")
    voyage_document_model: str = Field("voyage-4", alias="VOYAGE_DOCUMENT_MODEL")
    voyage_query_model: str = Field("voyage-4-lite", alias="VOYAGE_QUERY_MODEL")
    voyage_dimensions: int = Field(1024, alias="VOYAGE_DIMENSIONS")
    voyage_rerank_model: str = Field("rerank-2.5", alias="VOYAGE_RERANK_MODEL")
    voyage_base_url: str | None = Field(None, alias="VOYAGE_BASE_URL")

    # --- Tavily (web search) ---
    tavily_api_key: SecretStr | None = Field(None, alias="TAVILY_API_KEY")

    # --- Virtual filesystem ---
    vfs_backend: Literal["gridfs", "s3"] = Field("s3", alias="VFS_BACKEND")
    vfs_max_bytes: int = Field(50 * 1024 * 1024, alias="VFS_MAX_BYTES")
    vfs_s3_bucket: str | None = Field(None, alias="VFS_S3_BUCKET")
    vfs_s3_prefix: str = Field("deep-agent", alias="VFS_S3_PREFIX")
    vfs_s3_region: str | None = Field(None, alias="VFS_S3_REGION")

    # --- LangSmith ---
    langsmith_tracing: bool = Field(False, alias="LANGSMITH_TRACING")
    langsmith_api_key: SecretStr | None = Field(None, alias="LANGSMITH_API_KEY")
    langsmith_project: str = Field("deep_agent", alias="LANGSMITH_PROJECT")

    # --- Tunables ---
    semantic_cache_threshold: float = Field(0.9, alias="SEMANTIC_CACHE_THRESHOLD")
    max_steps: int = Field(32, alias="MAX_STEPS")
    # Budget for the deepagents planner's super-step recursion. /chat sets
    # RunnableConfig.recursion_limit to max(4 * max_hops, 50) so multi-step
    # plans ("plan + pull X + pull Y + draft Z") don't trip LangGraph's
    # default limit of 25. 20 hops * 4 super-steps = 80 is a comfortable floor.
    max_hops: int = Field(20, alias="MAX_HOPS")
    # Output token ceiling per LLM call. Claude emits ``tool_use`` blocks as
    # streaming JSON; when it hits the cap mid-emission the JSON is truncated
    # and pydantic rejects the partial input (e.g. ``write_file`` arriving
    # with no ``content`` field). Must be generous enough to fit the largest
    # plausible tool-call payload (typically a full ``write_file`` body).
    max_tokens: int = Field(32000, alias="MAX_TOKENS")

    # --- Collection names ---
    checkpoints_collection: str = "checkpoints"
    checkpoint_writes_collection: str = "checkpoint_writes"
    long_term_memory_collection: str = "long_term_memory"
    chat_history_collection: str = "chat_history"
    llm_cache_collection: str = "llm_cache"
    knowledge_base_collection: str = "knowledge_base"
    knowledge_graph_collection: str = "knowledge_graph"
    stream_events_collection: str = "stream_events"
    feedback_collection: str = "feedback"
    vfs_files_collection: str = "vfs_files"
    plans_collection: str = "plans"

    # --- Index names ---
    knowledge_base_vector_index: str = "vector_index"
    knowledge_base_search_index: str = "search_index"
    llm_cache_vector_index: str = "llm_cache_semantic_index"
    long_term_memory_vector_index: str = "memory_semantic_index"

    # --- Dev escape hatch ---
    allow_insecure: bool = Field(False, alias="ALLOW_INSECURE")

    # --- Domain pack selection (spec 200) ---
    domain: str = Field("reference", alias="DOMAIN")
    domains_root: Path = Field(default_factory=_default_domains_root, alias="DOMAINS_ROOT")

    @field_validator("voyage_dimensions")
    @classmethod
    def _positive_dims(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("voyage_dimensions must be positive")
        return v

    @field_validator("domain")
    @classmethod
    def _safe_domain(cls, v: str) -> str:
        if not v:
            raise ValueError("DOMAIN must be non-empty")
        if "/" in v or "\\" in v or ".." in Path(v).parts:
            raise ValueError(
                f"DOMAIN must be a plain directory name (no path separators or '..'), got: {v!r}"
            )
        return v

    @model_validator(mode="after")
    def _enforce_tls(self) -> Settings:
        uri = self.mongodb_uri.get_secret_value()
        is_srv = uri.startswith("mongodb+srv://")
        tls_flag = "tls=true" in uri.lower() or "ssl=true" in uri.lower()
        if not is_srv and not tls_flag and not self.allow_insecure:
            raise ValueError(
                "MONGODB_URI must enforce TLS (use mongodb+srv:// or include tls=true); "
                "set ALLOW_INSECURE=true to override for local dev."
            )
        return self

    @model_validator(mode="after")
    def _enforce_s3_config(self) -> Settings:
        if self.vfs_backend == "s3" and not self.vfs_s3_bucket:
            raise ValueError("VFS_BACKEND=s3 requires VFS_S3_BUCKET to be set")
        return self

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"<Settings db={self.mongodb_db} provider={self.llm_provider} "
            f"vfs={self.vfs_backend} [redacted]>"
        )

    __str__ = __repr__


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
