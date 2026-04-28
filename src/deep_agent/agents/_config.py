"""Helpers for reading per-request context out of LangGraph's ``RunnableConfig``.

The web server (spec 400) injects ``domain`` and ``db_name`` into
``RunnableConfig.configurable`` on every ``/chat`` call, and LangGraph
propagates the config down to every tool invocation. This module gives tools
a single extraction point so the "read domain from runtime" pattern lives in
one place rather than being copy-pasted into each tool file.

Every helper is safe to call outside a running graph — they return ``None``
(the single-domain / CLI default) instead of raising when ``get_config`` has
no active context.
"""
from __future__ import annotations

from typing import Any


def _configurable() -> dict[str, Any]:
    """Return the current ``RunnableConfig.configurable`` dict, or empty."""
    # Import lazily so this module is usable outside a LangGraph runtime (tests,
    # bare-Python tool invocations) without importing langgraph just to return {}.
    try:
        from langgraph.config import get_config
    except ImportError:  # pragma: no cover - langgraph always installed in this repo
        return {}
    try:
        cfg = get_config()
    except RuntimeError:
        return {}
    if not isinstance(cfg, dict):
        return {}
    configurable = cfg.get("configurable") or {}
    return configurable if isinstance(configurable, dict) else {}


def domain_from_config(config: Any = None) -> str | None:
    """Return ``configurable["domain"]`` or None.

    Accepts an explicit ``config`` for call sites that already have one in
    hand; otherwise reads the ambient ``RunnableConfig`` LangGraph injects
    into tool invocations.
    """
    if config is not None:
        inner = config.get("configurable") or {}
        val = inner.get("domain") if isinstance(inner, dict) else None
    else:
        val = _configurable().get("domain")
    return str(val) if isinstance(val, str) and val else None


def db_name_from_config(config: Any = None) -> str | None:
    """Return ``configurable["db_name"]`` or None.

    Prefer the explicit ``db_name`` injected by the server. Tools can fall
    back to ``domain_from_config`` + :func:`deep_agent.domain_pack.db_for`
    when ``db_name`` is absent but ``domain`` is present.
    """
    if config is not None:
        inner = config.get("configurable") or {}
        val = inner.get("db_name") if isinstance(inner, dict) else None
    else:
        val = _configurable().get("db_name")
    return str(val) if isinstance(val, str) and val else None


def resolved_db_name(config: Any = None) -> str | None:
    """Resolve the DB name from config, deriving it from ``domain`` if needed.

    Returns ``None`` when neither ``db_name`` nor ``domain`` is present, which
    tells the caller to use its own single-domain default (``Settings.mongodb_db``).
    """
    db = db_name_from_config(config)
    if db is not None:
        return db
    domain = domain_from_config(config)
    if domain is None:
        return None
    # Avoid a circular import: domain_pack imports config, which is the edge
    # of the typical cycle. agents/_config is downstream of both.
    from ..domain_pack import db_for

    return db_for(domain)
