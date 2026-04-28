"""Per-request domain resolution for FastAPI handlers.

Keeps the ``X-Domain`` validation logic in one place so ``/chat``, ``/plans``,
``/feedback``, and ``/health`` share a single definition of "what's a valid
domain pack".
"""
from __future__ import annotations

from fastapi import HTTPException, Request

from ..config import get_settings
from ..domain_pack import DomainPackError, _validate_name, list_available

_HEADER = "X-Domain"


def resolve_domain(request: Request) -> str:
    """Return the validated pack name for a request.

    Resolution order:
        ``X-Domain`` header → ``DOMAIN`` env var (``Settings.domain``).

    Raises ``HTTPException(400)`` if the resolved name is malformed (contains
    path separators or ``..``) or is not a currently-loadable pack.
    """
    raw = request.headers.get(_HEADER) or get_settings().domain
    try:
        _validate_name(raw)
    except DomainPackError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    installed = {p["name"] for p in list_available()}
    if raw not in installed:
        raise HTTPException(
            status_code=400,
            detail=f"unknown domain: {raw}; available: {sorted(installed)}",
        )
    return raw
