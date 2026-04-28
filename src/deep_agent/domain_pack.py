"""Domain-pack loader (spec 200, extended by spec 400).

A pack is a self-contained directory under ``domains/<name>/`` holding:

- ``pack.yaml`` - manifest with ``name``, ``description``, ``allow_list``
- ``prompts.py`` - exports ``MAIN_PROMPT`` and ``RESEARCHER_PROMPT``
- ``seeds/`` - ``knowledge_base.json``, ``knowledge_graph.json``, ``operational/*.json``
- ``README.md`` - operator-facing pack description (optional at runtime)

Pack selection:

- Default (CLI / worker / ``langgraph dev``): the ``DOMAIN`` env var drives
  :class:`Settings.domain`; :func:`get_active_pack` resolves that name.
- Multi-domain web server (spec 400): each HTTP request passes an explicit
  ``domain=<name>``. Packs are cached per distinct name so one process can
  serve every pack concurrently.

Tests that swap packs on disk must call :func:`clear_active_pack_cache` (which
drops the keyed cache entirely) and ``get_settings.cache_clear()``.
"""
from __future__ import annotations

import importlib.util
import logging
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .config import get_settings

log = logging.getLogger(__name__)

_REQUIRED_YAML_KEYS: tuple[str, ...] = ("name", "description", "allow_list")
_REQUIRED_PROMPTS: tuple[str, ...] = ("MAIN_PROMPT", "RESEARCHER_PROMPT")


class DomainPackError(RuntimeError):
    """Raised when a domain pack cannot be loaded or is malformed."""


@dataclass(frozen=True)
class DomainPrompts:
    main: str
    researcher: str


@dataclass(frozen=True)
class DomainPack:
    name: str
    description: str
    allow_list: frozenset[str]
    seeds_dir: Path
    prompts: DomainPrompts


def _validate_name(name: str) -> None:
    """Reject names that would allow path traversal or escape DOMAINS_ROOT.

    Mirrors ``Settings._safe_domain`` so the rule lives in one place and
    applies uniformly to env-driven and header-driven resolution.
    """
    if not isinstance(name, str) or not name:
        raise DomainPackError("domain name must be a non-empty string")
    if "/" in name or "\\" in name or ".." in Path(name).parts:
        raise DomainPackError(
            f"domain name must be a plain directory (no '/', '\\\\', or '..'), got: {name!r}"
        )


def _load_manifest(pack_yaml: Path, expected_name: str) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(pack_yaml.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise DomainPackError(f"{pack_yaml} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise DomainPackError(f"{pack_yaml} must be a YAML mapping at top level")

    for key in _REQUIRED_YAML_KEYS:
        if key not in raw:
            raise DomainPackError(f"{pack_yaml} missing required key: {key!r}")

    name = raw["name"]
    description = raw["description"]
    allow_list = raw["allow_list"]

    if not isinstance(name, str) or not name:
        raise DomainPackError(f"{pack_yaml}: 'name' must be a non-empty string")
    if name != expected_name:
        raise DomainPackError(
            f"{pack_yaml}: 'name' ({name!r}) must match directory ({expected_name!r})"
        )
    if not isinstance(description, str) or not description.strip():
        raise DomainPackError(f"{pack_yaml}: 'description' must be a non-empty string")
    if not isinstance(allow_list, list) or not all(isinstance(x, str) for x in allow_list):
        raise DomainPackError(f"{pack_yaml}: 'allow_list' must be a list of strings")

    return raw


def _load_prompts(prompts_py: Path, pack_name: str) -> DomainPrompts:
    mod_name = f"_deep_agent_pack_{pack_name}"
    spec = importlib.util.spec_from_file_location(mod_name, prompts_py)
    if spec is None or spec.loader is None:
        raise DomainPackError(f"cannot load {prompts_py}")
    module = importlib.util.module_from_spec(spec)
    # Register so introspection tools can find it; overwrite any prior pack module.
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - exotic failures
        raise DomainPackError(f"failed to import {prompts_py}: {exc}") from exc

    missing = [c for c in _REQUIRED_PROMPTS if not isinstance(getattr(module, c, None), str)]
    if missing:
        raise DomainPackError(
            f"{prompts_py} missing required string constant(s): {', '.join(missing)}"
        )
    return DomainPrompts(
        main=str(module.MAIN_PROMPT),
        researcher=str(module.RESEARCHER_PROMPT),
    )


def load_pack(domains_root: Path, domain: str) -> DomainPack:
    """Load a pack by absolute root + name. Uncached; used by tests and
    :func:`_load_pack`."""
    root_resolved = domains_root.resolve()
    pack_dir = (domains_root / domain).resolve()

    # Belt-and-braces path-containment check (Settings already rejects traversal).
    try:
        pack_dir.relative_to(root_resolved)
    except ValueError as exc:
        raise DomainPackError(
            f"pack directory {pack_dir} is outside DOMAINS_ROOT {root_resolved}"
        ) from exc

    pack_yaml = pack_dir / "pack.yaml"
    prompts_py = pack_dir / "prompts.py"

    if not pack_dir.is_dir():
        raise DomainPackError(f"pack directory not found: {pack_dir}")
    if not pack_yaml.is_file():
        raise DomainPackError(f"missing pack.yaml: {pack_yaml}")
    if not prompts_py.is_file():
        raise DomainPackError(f"missing prompts.py: {prompts_py}")

    meta = _load_manifest(pack_yaml, expected_name=domain)
    prompts = _load_prompts(prompts_py, pack_name=domain)

    return DomainPack(
        name=str(meta["name"]),
        description=str(meta["description"]),
        allow_list=frozenset(str(x) for x in meta["allow_list"]),
        seeds_dir=pack_dir / "seeds",
        prompts=prompts,
    )


@lru_cache(maxsize=16)
def _load_pack(name: str) -> DomainPack:
    """Inner cache keyed on the resolved (non-None) pack name.

    Multi-domain web server holds several packs simultaneously in this cache.
    """
    _validate_name(name)
    return load_pack(get_settings().domains_root, name)


def get_active_pack(domain: str | None = None) -> DomainPack:
    """Load and cache a domain pack by name.

    ``domain=None`` resolves to ``Settings.domain`` (env-driven default) — the
    backward-compatible path used by the CLI and worker. An explicit ``domain``
    argument bypasses the env and is cached independently so a multi-domain
    server can hold several packs simultaneously. The cache key is the
    resolved name, so no-arg and explicit-arg calls targeting the same pack
    share one cached object.
    """
    name = domain if domain is not None else get_settings().domain
    return _load_pack(name)


def clear_active_pack_cache() -> None:
    """Drop the cached packs. Used by tests that swap ``DOMAIN`` or rewrite
    packs on disk, and by CLI code paths that rotate domains within one
    process (rare outside tests)."""
    _load_pack.cache_clear()


def list_available() -> list[dict[str, str]]:
    """Return ``[{name, description}]`` for every loadable pack under ``DOMAINS_ROOT``.

    Entries are sorted by directory name so output is deterministic. Pack
    directories that cannot be loaded (malformed YAML, missing prompts.py,
    missing required keys) are silently skipped with a warning logged — the
    caller (e.g. ``GET /domains``) must never crash because one pack on
    disk is broken.
    """
    root = get_settings().domains_root
    if not root.is_dir():
        return []
    out: list[dict[str, str]] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        if name.startswith(".") or name.startswith("_"):
            continue
        try:
            _validate_name(name)
            pack = _load_pack(name)
        except DomainPackError as exc:
            log.warning("skipping malformed pack %r: %s", name, exc)
            continue
        out.append({"name": name, "description": pack.description})
    return out


def db_for(domain: str | None = None) -> str:
    """Compute the MongoDB database name for ``domain``.

    - ``db_for(None)``  →  ``Settings.mongodb_db`` verbatim (CLI / worker
      path; preserves existing single-domain install).
    - ``db_for(<pack>)``  →  ``{prefix}_{pack}`` where ``prefix`` is
      ``Settings.mongodb_db`` with any trailing underscore stripped.

    This lets operators keep ``MONGODB_DB=deep_agent`` in multi-domain (web)
    mode — the suffix is appended per request — or ``MONGODB_DB=deep_agent_<pack>``
    in single-domain mode, where no ``X-Domain`` header arrives and the
    server never calls :func:`db_for` with a non-None name.
    """
    s = get_settings()
    if domain is None:
        return s.mongodb_db
    _validate_name(domain)
    prefix = (s.mongodb_db or "deep_agent").rstrip("_")
    return f"{prefix}_{domain}"
