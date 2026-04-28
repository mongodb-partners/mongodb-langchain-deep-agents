"""FastAPI application exposing the deep-agent graph.

Endpoints:
- ``GET  /health``    — pings MongoDB, echoes the active pack + DB.
- ``GET  /domains``   — lists available domain packs (drives the UI selector).
- ``GET  /plans``     — returns the latest planner todo snapshot for a thread.
- ``POST /chat``      — streams tokens via SSE from ``graph.astream_events``.
  The active domain is resolved per request from the ``X-Domain`` header
  (falls back to env ``DOMAIN``). Thread IDs are scoped by domain so
  checkpoint state and chat history don't bleed across packs.
- ``POST /feedback``  — persists run feedback to MongoDB (domain-aware) and
  mirrors to LangSmith when tracing is enabled.

The ``/chat`` handler deliberately does NOT wrap the graph stream in
``ascoped_semantic_cache`` — LangChain's ``set_llm_cache`` mutates a
process-global that can only be swapped under a serializing lock, which in
the sibling repo measured a ~5x wall-time regression against 5-domain
parallel traffic. See spec 400 decision D-404.
"""
from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field
from pymongo.errors import PyMongoError
from sse_starlette.sse import EventSourceResponse

from ..config import get_settings
from ..domain_pack import db_for, list_available
from ..graph import build_graph
from ..persistence.chat_history import build_chat_history
from ..persistence.indexes import ensure_indexes
from ..persistence.mongo import get_client, get_db
from ..persistence.plans import load_plan_snapshot, persist_plan_snapshot
from .domain import resolve_domain

log = logging.getLogger(__name__)


def _token_text(content: Any) -> str:
    """Project an LLM chunk's ``content`` down to a plain-text slice.

    Bedrock Anthropic streams ``AIMessageChunk.content`` as either a bare
    string (final writer prose) or a list of structured blocks —
    ``[{"type": "text", "text": "..."}, {"type": "tool_use", "input": {...}}]``.
    Only ``text`` blocks are user-visible; forwarding ``tool_use`` scaffolding
    to the browser dumps Python-repr garbage into the chat bubble. The
    planner + subagents produce these too (every tool call), so we filter
    at the SSE boundary.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


class ChatRequest(BaseModel):
    user_id: str = Field(..., description="Required: scopes memory + enforces auth boundary")
    thread_id: str | None = Field(None, description="Optional checkpoint/thread ID (resumes state)")
    message: str


class FeedbackRequest(BaseModel):
    run_id: str
    score: float
    comment: str | None = None
    user_id: str


def _cors_origins() -> list[str]:
    """Permissive in dev, strict in prod.

    ``ALLOW_INSECURE=true`` → ``['*']`` (local demo / CI). Otherwise the
    backend only trusts ``FRONTEND_ORIGIN`` (default ``http://localhost:3000``).
    """
    if get_settings().allow_insecure:
        return ["*"]
    return [os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")]


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Provision domain-specific databases and indexes on startup."""
    for pack in list_available():
        db_name = db_for(pack["name"])
        log.info("ensuring indexes for %s (db=%s)", pack["name"], db_name)
        try:
            ensure_indexes(db_name=db_name)
        except Exception:
            log.warning("index provisioning failed for %s", db_name, exc_info=True)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="deep_agent", version="0.1.0", lifespan=_lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health(request: Request) -> dict[str, Any]:
        domain = resolve_domain(request)
        db_name = db_for(domain)
        s = get_settings()
        try:
            get_client().admin.command("ping")
            mongo_ok = "ok"
        except (PyMongoError, ConnectionError) as exc:
            mongo_ok = f"error: {type(exc).__name__}"
        return {
            "mongo": mongo_ok,
            "db": db_name,
            "domain": domain,
            "llm_model": s.llm_model,
            "ts": datetime.now(UTC).isoformat(),
        }

    @app.get("/domains")
    def domains() -> dict[str, Any]:
        return {"domains": list_available()}

    @app.get("/plans")
    def plans(user_id: str, thread_id: str, request: Request) -> dict[str, Any]:
        """Return the latest planner todo snapshot for ``(user_id, thread_id)``.

        Always returns 200 with ``{"todos": [...], "updated_at": <iso | null>}`` —
        a missing snapshot yields an empty list (REQ-E-EC-405). The web UI
        polls this after every SSE ``done`` frame to populate the Plan drawer.
        """
        domain = resolve_domain(request)
        db_name = db_for(domain)
        return load_plan_snapshot(user_id, thread_id, db_name=db_name)

    @app.post("/chat")
    async def chat(req: ChatRequest, request: Request) -> EventSourceResponse:
        from langchain_core.messages import HumanMessage

        domain = resolve_domain(request)
        db_name = db_for(domain)
        graph = build_graph(domain=domain)

        # thread_id is {user_id}:{domain}:{sub}. Including domain prevents
        # checkpoint, chat-history, plans, and VFS rows from bleeding across
        # packs when the same user chats under multiple domains.
        sub = req.thread_id or "default"
        thread_id = f"{req.user_id}:{domain}:{sub}"

        # LangGraph's default recursion_limit (25 super-steps) is too low for
        # multi-step planner prompts ("plan a workup: pull X + pull Y + draft Z").
        # Budget 4 super-steps per hop, floor at 50, matching the sibling repo.
        recursion_limit = max(4 * get_settings().max_hops, 50)
        config: RunnableConfig = {
            "configurable": {
                "thread_id": thread_id,
                "user_id": req.user_id,
                "domain": domain,
                "db_name": db_name,
            },
            "recursion_limit": recursion_limit,
        }
        input_state = {
            "messages": [HumanMessage(content=req.message)],
            "user_id": req.user_id,
        }

        history = build_chat_history(thread_id, db_name=db_name)
        try:
            history.add_user_message(req.message)
        except PyMongoError:
            log.warning("chat_history append (user) failed", exc_info=True)

        async def _event_stream() -> AsyncGenerator[dict[str, Any], None]:
            collected: list[str] = []
            try:
                # Note: we deliberately do NOT wrap the stream in
                # ascoped_semantic_cache(db_name). See module docstring +
                # spec 400 D-404. The scoped managers exist for CLI / future
                # use; the web path is cacheless.
                async for event in graph.astream_events(
                    input_state, config=config, version="v2"
                ):
                    if event.get("event") == "on_chat_model_stream":
                        chunk = event["data"].get("chunk")
                        text = _token_text(getattr(chunk, "content", None))
                        if text:
                            collected.append(text)
                            yield {"event": "token", "data": text}
                final = "".join(collected)
                if final:
                    try:
                        history.add_ai_message(final)
                    except PyMongoError:
                        log.warning("chat_history append (ai) failed", exc_info=True)

                # Best-effort plan snapshot — the turn already succeeded.
                with contextlib.suppress(Exception):
                    state = graph.get_state(config).values
                    persist_plan_snapshot(
                        state,
                        user_id=req.user_id,
                        thread_id=thread_id,
                        db_name=db_name,
                    )

                yield {"event": "done", "data": "[DONE]"}
            except Exception as exc:
                # SSE boundary: surface graph errors as error frames.
                log.exception("chat stream failed")
                yield {"event": "error", "data": f"{type(exc).__name__}: {exc}"}

        return EventSourceResponse(_event_stream())

    @app.post("/feedback")
    def feedback(req: FeedbackRequest, request: Request) -> dict[str, Any]:
        s = get_settings()
        domain = resolve_domain(request)
        db_name = db_for(domain)
        doc = {
            "run_id": req.run_id,
            "score": req.score,
            "comment": req.comment,
            "user_id": req.user_id,
            "domain": domain,
            "created_at": datetime.now(UTC),
        }
        try:
            get_db(db_name)[s.feedback_collection].insert_one(doc)
        except PyMongoError as exc:
            log.exception("failed to persist feedback")
            raise HTTPException(status_code=500, detail="failed to persist feedback") from exc

        if s.langsmith_tracing:
            try:
                from langsmith import Client

                Client().create_feedback(
                    run_id=req.run_id,
                    key="user_score",
                    score=req.score,
                    comment=req.comment,
                )
            except Exception:
                # LangSmith mirror is best-effort.
                log.warning("LangSmith feedback mirror failed", exc_info=True)

        return {"ok": True}

    return app


app: FastAPI | None = None


def get_asgi_app() -> FastAPI:  # pragma: no cover - uvicorn entrypoint
    global app
    if app is None:
        app = create_app()
    return app
