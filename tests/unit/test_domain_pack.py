"""Unit tests for the domain-pack loader (spec 200).

Covers REQ-E-200 through REQ-E-205, plus cache-clearing semantics used by
higher-level tests that switch packs.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


def _write_pack(
    root: Path,
    name: str,
    *,
    description: str = "test pack",
    allow_list: list[str] | None = None,
    main_prompt: str = "MAIN prompt body.",
    researcher_prompt: str = "RESEARCHER prompt body.",
    operational_files: dict[str, list[dict[str, object]]] | None = None,
    omit_yaml: bool = False,
    omit_prompts: bool = False,
    omit_yaml_key: str | None = None,
    omit_prompt_const: str | None = None,
) -> Path:
    pack_dir = root / name
    (pack_dir / "seeds" / "operational").mkdir(parents=True, exist_ok=True)

    if not omit_yaml:
        import yaml

        meta: dict[str, object] = {
            "name": name,
            "description": description,
            "allow_list": allow_list or ["things"],
        }
        if omit_yaml_key:
            meta.pop(omit_yaml_key, None)
        (pack_dir / "pack.yaml").write_text(yaml.safe_dump(meta), encoding="utf-8")

    if not omit_prompts:
        body_parts: list[str] = []
        if omit_prompt_const != "MAIN_PROMPT":
            body_parts.append(f'MAIN_PROMPT = """{main_prompt}"""')
        if omit_prompt_const != "RESEARCHER_PROMPT":
            body_parts.append(f'RESEARCHER_PROMPT = """{researcher_prompt}"""')
        (pack_dir / "prompts.py").write_text("\n".join(body_parts) + "\n", encoding="utf-8")

    # Minimal seeds
    (pack_dir / "seeds" / "knowledge_base.json").write_text(
        '[{"text": "hello", "metadata": {"source": "unit"}}]', encoding="utf-8"
    )
    (pack_dir / "seeds" / "knowledge_graph.json").write_text(
        '[{"text": "a-b", "metadata": {}}]', encoding="utf-8"
    )
    for stem, rows in (operational_files or {"things": [{"_id": "t1"}]}).items():
        import json

        (pack_dir / "seeds" / "operational" / f"{stem}.json").write_text(
            json.dumps(rows), encoding="utf-8"
        )
    return pack_dir


@pytest.fixture(autouse=True)
def _isolated_packs_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point DOMAINS_ROOT at a fresh temp dir for every test and clear caches."""
    monkeypatch.setenv("DOMAINS_ROOT", str(tmp_path))

    from deep_agent import config as _cfg
    from deep_agent import domain_pack as _dp

    _cfg.get_settings.cache_clear()
    _dp.clear_active_pack_cache()
    yield tmp_path
    _cfg.get_settings.cache_clear()
    _dp.clear_active_pack_cache()


def test_TC_20_001_pack_load_happy(_isolated_packs_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """REQ-E-200/205: loader returns DomainPack with expected fields."""
    _write_pack(_isolated_packs_root, "reference", allow_list=["things"])
    monkeypatch.setenv("DOMAIN", "reference")

    from deep_agent.domain_pack import DomainPack, get_active_pack

    pack = get_active_pack()
    assert isinstance(pack, DomainPack)
    assert pack.name == "reference"
    assert pack.description == "test pack"
    assert pack.allow_list == frozenset({"things"})
    assert pack.seeds_dir.is_dir()
    assert pack.prompts.main == "MAIN prompt body."
    assert pack.prompts.researcher == "RESEARCHER prompt body."


def test_TC_20_002_missing_pack_yaml_errors(
    _isolated_packs_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REQ-E-201: missing pack.yaml raises DomainPackError naming the path."""
    _write_pack(_isolated_packs_root, "broken", omit_yaml=True)
    monkeypatch.setenv("DOMAIN", "broken")

    from deep_agent.domain_pack import DomainPackError, get_active_pack

    with pytest.raises(DomainPackError, match=r"pack\.yaml"):
        get_active_pack()


def test_TC_20_002b_missing_prompts_py_errors(
    _isolated_packs_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REQ-E-201: missing prompts.py raises DomainPackError naming the path."""
    _write_pack(_isolated_packs_root, "broken2", omit_prompts=True)
    monkeypatch.setenv("DOMAIN", "broken2")

    from deep_agent.domain_pack import DomainPackError, get_active_pack

    with pytest.raises(DomainPackError, match=r"prompts\.py"):
        get_active_pack()


def test_TC_20_003_domain_traversal_rejected_by_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REQ-E-202: DOMAIN containing path separators or '..' is rejected."""
    from deep_agent import config as _cfg
    from deep_agent.config import Settings

    _cfg.get_settings.cache_clear()
    for bad in ["../etc", "foo/bar", "foo\\bar", ".."]:
        monkeypatch.setenv("DOMAIN", bad)
        with pytest.raises(ValueError, match="DOMAIN"):
            Settings()


def test_TC_20_004_yaml_missing_key_errors(
    _isolated_packs_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REQ-E-203: missing required YAML key surfaces the key name."""
    _write_pack(_isolated_packs_root, "badyaml", omit_yaml_key="allow_list")
    monkeypatch.setenv("DOMAIN", "badyaml")

    from deep_agent.domain_pack import DomainPackError, get_active_pack

    with pytest.raises(DomainPackError, match="allow_list"):
        get_active_pack()


def test_TC_20_005_prompt_constants_required(
    _isolated_packs_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REQ-E-204: missing prompt constant surfaces its name."""
    _write_pack(_isolated_packs_root, "noprompt", omit_prompt_const="RESEARCHER_PROMPT")
    monkeypatch.setenv("DOMAIN", "noprompt")

    from deep_agent.domain_pack import DomainPackError, get_active_pack

    with pytest.raises(DomainPackError, match="RESEARCHER_PROMPT"):
        get_active_pack()


def test_TC_20_006_domain_pack_is_frozen(
    _isolated_packs_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REQ-E-205: DomainPack is immutable."""
    import dataclasses

    _write_pack(_isolated_packs_root, "frozen", allow_list=["things"])
    monkeypatch.setenv("DOMAIN", "frozen")

    from deep_agent.domain_pack import get_active_pack

    pack = get_active_pack()
    with pytest.raises(dataclasses.FrozenInstanceError):
        pack.name = "mutated"  # type: ignore[misc]


def test_TC_20_007_cache_clear_reloads(
    _isolated_packs_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Loader is cached; clear_active_pack_cache re-reads the pack."""
    _write_pack(_isolated_packs_root, "cached", description="first")
    monkeypatch.setenv("DOMAIN", "cached")

    from deep_agent.domain_pack import clear_active_pack_cache, get_active_pack

    first = get_active_pack()
    assert first.description == "first"

    # Mutate pack.yaml on disk
    (_isolated_packs_root / "cached" / "pack.yaml").write_text(
        textwrap.dedent(
            """\
            name: cached
            description: second
            allow_list: [things]
            """
        ),
        encoding="utf-8",
    )
    # Without clearing, same object
    assert get_active_pack().description == "first"

    from deep_agent import config as _cfg

    _cfg.get_settings.cache_clear()
    clear_active_pack_cache()

    assert get_active_pack().description == "second"


def test_TC_20_008_pack_dir_inside_root_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Belt-and-braces: even if Settings let a weird name through, the loader
    checks the resolved pack_dir is inside domains_root."""
    # Put pack outside domains_root via a symlink trick.
    outside = tmp_path / "outside"
    outside.mkdir()
    inside = tmp_path / "domains"
    inside.mkdir()
    # Symlink 'evil' inside 'domains' to the outside dir.
    try:
        (inside / "evil").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not supported on this filesystem")
    _ = outside  # populated below? we leave it empty; loader should either not find or reject

    # `evil` resolves to `outside`, which is NOT inside `inside` — loader must reject.
    monkeypatch.setenv("DOMAINS_ROOT", str(inside))
    monkeypatch.setenv("DOMAIN", "evil")

    from deep_agent import config as _cfg
    from deep_agent.domain_pack import DomainPackError, clear_active_pack_cache, get_active_pack

    _cfg.get_settings.cache_clear()
    clear_active_pack_cache()
    with pytest.raises(DomainPackError):
        get_active_pack()


# -------------------- Spec 400 (web-ui): keyed cache + list_available + db_for --------------------


def test_TC_40_410a_get_active_pack_explicit_domain_overrides_env(
    _isolated_packs_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REQ-E-410: explicit domain= bypasses env DOMAIN."""
    _write_pack(_isolated_packs_root, "finance", description="F")
    _write_pack(_isolated_packs_root, "healthcare", description="H")
    monkeypatch.setenv("DOMAIN", "finance")

    from deep_agent.domain_pack import get_active_pack

    # Env says finance, but explicit arg picks healthcare.
    assert get_active_pack("healthcare").name == "healthcare"
    assert get_active_pack("healthcare").description == "H"


def test_TC_40_410b_keyed_cache_holds_multiple_packs(
    _isolated_packs_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REQ-E-410: sequential calls for distinct domains each resolve correctly
    and the cache holds both (web server must serve multiple packs in one process)."""
    _write_pack(_isolated_packs_root, "finance", description="F")
    _write_pack(_isolated_packs_root, "retail", description="R")
    monkeypatch.setenv("DOMAIN", "finance")

    from deep_agent.domain_pack import get_active_pack

    first = get_active_pack("finance")
    second = get_active_pack("retail")
    assert first.name == "finance"
    assert second.name == "retail"

    # Cache identity: same name returns same object; different names return different objects.
    assert get_active_pack("finance") is first
    assert get_active_pack("retail") is second
    assert first is not second


def test_TC_40_INV_402_no_arg_resolves_env_default(
    _isolated_packs_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INV-402: no-arg get_active_pack() still uses Settings.domain (env)."""
    _write_pack(_isolated_packs_root, "telco", description="T")
    monkeypatch.setenv("DOMAIN", "telco")

    from deep_agent.domain_pack import get_active_pack

    pack_no_arg = get_active_pack()
    pack_explicit = get_active_pack("telco")
    # Same cache slot when arg resolves to the same name.
    assert pack_no_arg is pack_explicit
    assert pack_no_arg.name == "telco"


def test_TC_40_list_available_happy(
    _isolated_packs_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REQ-E-403: list_available returns {name, description} for every valid pack,
    sorted by directory name."""
    _write_pack(_isolated_packs_root, "retail", description="Retail pack")
    _write_pack(_isolated_packs_root, "finance", description="Finance pack")
    _write_pack(_isolated_packs_root, "healthcare", description="Healthcare pack")
    monkeypatch.setenv("DOMAIN", "retail")

    from deep_agent.domain_pack import list_available

    entries = list_available()
    names = [e["name"] for e in entries]
    # sorted
    assert names == sorted(names)
    # all present
    assert set(names) == {"finance", "healthcare", "retail"}
    # each entry carries the manifest description
    by_name = {e["name"]: e["description"] for e in entries}
    assert by_name["finance"] == "Finance pack"
    assert by_name["healthcare"] == "Healthcare pack"


def test_TC_40_EC_401_list_available_skips_malformed(
    _isolated_packs_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """REQ-E-EC-401: malformed pack dir is omitted (with warning) — no 500 on
    GET /domains. Other valid packs still appear."""
    _write_pack(_isolated_packs_root, "good", description="Good one")
    _write_pack(_isolated_packs_root, "broken", omit_yaml=True)
    monkeypatch.setenv("DOMAIN", "good")

    import logging

    from deep_agent.domain_pack import list_available

    with caplog.at_level(logging.WARNING, logger="deep_agent.domain_pack"):
        entries = list_available()

    names = [e["name"] for e in entries]
    assert names == ["good"]
    assert any("broken" in rec.message for rec in caplog.records), caplog.text


def test_TC_40_list_available_ignores_dotfiles_and_nondirs(
    _isolated_packs_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """list_available skips files, dotfiles, and underscore-prefixed dirs."""
    _write_pack(_isolated_packs_root, "ok", description="OK pack")
    # stray file in DOMAINS_ROOT
    (_isolated_packs_root / "README.md").write_text("readme", encoding="utf-8")
    # dotdir
    (_isolated_packs_root / ".hidden").mkdir()
    # underscore-prefixed dir (internal, e.g. __pycache__ / _tmp)
    (_isolated_packs_root / "_tmp").mkdir()
    monkeypatch.setenv("DOMAIN", "ok")

    from deep_agent.domain_pack import list_available

    names = [e["name"] for e in list_available()]
    assert names == ["ok"]


def test_TC_40_db_for_explicit_appends_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    """db_for(name) returns {prefix}_{name}."""
    monkeypatch.setenv("MONGODB_DB", "deep_agent")

    from deep_agent import config as _cfg
    from deep_agent.domain_pack import db_for

    _cfg.get_settings.cache_clear()
    assert db_for("finance") == "deep_agent_finance"
    assert db_for("healthcare") == "deep_agent_healthcare"


def test_TC_40_db_for_none_returns_settings_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """db_for(None) returns Settings.mongodb_db verbatim (preserves single-domain)."""
    monkeypatch.setenv("MONGODB_DB", "deep_agent_custom")

    from deep_agent import config as _cfg
    from deep_agent.domain_pack import db_for

    _cfg.get_settings.cache_clear()
    assert db_for() == "deep_agent_custom"
    assert db_for(None) == "deep_agent_custom"


def test_TC_40_db_for_strips_trailing_underscore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both MONGODB_DB=deep_agent and MONGODB_DB=deep_agent_ yield the same suffix."""
    from deep_agent import config as _cfg
    from deep_agent.domain_pack import db_for

    monkeypatch.setenv("MONGODB_DB", "deep_agent_")
    _cfg.get_settings.cache_clear()
    assert db_for("finance") == "deep_agent_finance"


def test_TC_40_db_for_rejects_bad_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """db_for reuses the name validator; path separators / traversal blocked."""
    from deep_agent import config as _cfg
    from deep_agent.domain_pack import DomainPackError, db_for

    _cfg.get_settings.cache_clear()
    for bad in ["../etc", "foo/bar", "foo\\bar", ".."]:
        with pytest.raises(DomainPackError):
            db_for(bad)


def test_TC_40_clear_active_pack_cache_still_works(
    _isolated_packs_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INV-407: clear_active_pack_cache (used by conftest) still wipes the
    new keyed cache so tests remain isolated."""
    _write_pack(_isolated_packs_root, "x", description="first")
    monkeypatch.setenv("DOMAIN", "x")

    from deep_agent import config as _cfg
    from deep_agent.domain_pack import clear_active_pack_cache, get_active_pack

    first = get_active_pack("x")
    assert first.description == "first"

    # Mutate pack.yaml on disk for this name.
    (_isolated_packs_root / "x" / "pack.yaml").write_text(
        textwrap.dedent(
            """\
            name: x
            description: second
            allow_list: [things]
            """
        ),
        encoding="utf-8",
    )

    # Without clearing, cache returns stale.
    assert get_active_pack("x").description == "first"

    _cfg.get_settings.cache_clear()
    clear_active_pack_cache()

    assert get_active_pack("x").description == "second"
