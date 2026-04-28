"""Singleton MongoDB client + database handle."""
from __future__ import annotations

from typing import Any

from pymongo import MongoClient
from pymongo.errors import ConfigurationError, PyMongoError

from ..config import get_settings

_singleton_client: MongoClient[dict[str, Any]] | None = None


def get_client() -> MongoClient[dict[str, Any]]:
    """Return a process-wide singleton :class:`pymongo.MongoClient`.

    On first call, connects using ``MONGODB_URI``. Subsequent calls return the
    cached instance. Connection failures raise :class:`ConnectionError` with the
    URI redacted.
    """
    global _singleton_client
    if _singleton_client is not None:
        return _singleton_client
    s = get_settings()
    try:
        _singleton_client = MongoClient(s.mongodb_uri.get_secret_value())
    except (PyMongoError, ConfigurationError, ValueError) as exc:
        raise ConnectionError(
            f"Failed to connect to MongoDB: {type(exc).__name__}: [URI redacted]"
        ) from None
    return _singleton_client


def get_db(db_name: str | None = None) -> Any:
    """Return the :class:`pymongo.database.Database` for ``db_name``.

    ``db_name=None`` uses ``Settings.mongodb_db`` — preserves the CLI / worker's
    single-database behavior. The multi-domain web server passes a per-request
    db_name (e.g. ``deep_agent_<pack>``) derived from the active pack name.
    """
    name = db_name if db_name is not None else get_settings().mongodb_db
    return get_client()[name]


def reset_for_tests() -> None:
    """Clear the singleton. Intended for test fixtures only."""
    global _singleton_client
    _singleton_client = None
