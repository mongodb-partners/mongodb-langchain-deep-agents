"""Command-line entrypoint.

Subcommands:
- ``chat``  — REPL or one-shot invocation against the compiled deep-agent graph.
- ``seed``  — run the seed loader.
- ``serve`` — boot the FastAPI application via uvicorn.

Examples:

    deep-agent chat --once "Research X." --user alice
    deep-agent seed
    deep-agent serve --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import argparse
import contextlib
import logging
import os
import sys

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from pymongo.errors import PyMongoError

from .domain_pack import db_for, get_active_pack
from .graph import build_graph
from .persistence.chat_history import build_chat_history
from .persistence.plans import persist_plan_snapshot

log = logging.getLogger(__name__)


def _run_chat(args: argparse.Namespace) -> int:
    domain = get_active_pack().name
    db_name = db_for(domain)
    graph = build_graph(domain=domain)
    history = build_chat_history(args.thread, db_name=db_name)
    config: RunnableConfig = {
        "configurable": {
            "thread_id": args.thread,
            "user_id": args.user,
            "domain": domain,
            "db_name": db_name,
        }
    }

    def invoke(message: str) -> str:
        try:
            history.add_user_message(message)
        except PyMongoError:
            log.warning("chat_history append (user) failed", exc_info=True)
        state = graph.invoke(
            {
                "messages": [HumanMessage(content=message)],
                "user_id": args.user,
            },
            config=config,
        )
        msgs = state.get("messages", []) if isinstance(state, dict) else []
        answer = ""
        for m in reversed(msgs):
            if isinstance(m, AIMessage):
                answer = str(m.content)
                break
        if answer:
            try:
                history.add_ai_message(answer)
            except PyMongoError:
                log.warning("chat_history append (ai) failed", exc_info=True)

        # Plan persistence is best-effort so the turn still succeeds when the
        # `plans` collection is temporarily unavailable.
        with contextlib.suppress(Exception):
            persist_plan_snapshot(
                state, user_id=args.user, thread_id=args.thread, db_name=db_name
            )
        return answer

    if args.once is not None:
        print(invoke(args.once))
        return 0

    print(f"deep-agent chat (user={args.user}, thread={args.thread}) — Ctrl-D to exit")
    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            print()
            return 0
        if not line:
            continue
        if line in {"/quit", "/exit"}:
            return 0
        print(invoke(line))


def _run_seed(_: argparse.Namespace) -> int:
    from .domain_pack import get_active_pack
    from .ingestion.seed import seed_all

    print(f"[deep-agent] active pack: {get_active_pack().name}")
    print(seed_all())
    return 0


def _run_serve(args: argparse.Namespace) -> int:  # pragma: no cover - e2e only
    import uvicorn

    uvicorn.run(
        "deep_agent.server.app:get_asgi_app",
        host=args.host,
        port=args.port,
        factory=True,
        reload=args.reload,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="deep-agent")
    p.add_argument(
        "--domain",
        default=None,
        help="Active domain pack (sets DOMAIN env for this invocation).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    chat = sub.add_parser("chat", help="interactive REPL or --once invocation")
    chat.add_argument("--once", type=str, default=None, help="run a single prompt and exit")
    chat.add_argument("--user", type=str, default="demo-user", help="user_id for memory scoping")
    chat.add_argument("--thread", type=str, default="cli-default", help="thread_id (checkpoint key)")
    chat.set_defaults(func=_run_chat)

    seed = sub.add_parser("seed", help="load domain seeds into Atlas")
    seed.set_defaults(func=_run_seed)

    serve = sub.add_parser("serve", help="boot the FastAPI app")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(func=_run_serve)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.domain:
        # Set BEFORE any call that reaches get_settings() so the cached
        # Settings instance sees the override.
        os.environ["DOMAIN"] = args.domain
        from . import config as _cfg
        from . import domain_pack as _dp

        _cfg.get_settings.cache_clear()
        _dp.clear_active_pack_cache()
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
