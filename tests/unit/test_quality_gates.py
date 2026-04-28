"""Sub-phase 15: lint, typecheck, and domain-isolation quality gates."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_TC_15_040_ruff_clean() -> None:
    if shutil.which("ruff") is None:
        pytest.skip("ruff not installed")
    r = subprocess.run(
        ["ruff", "check", "src", "tests", "streaming/producer.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"ruff failed:\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"


def test_TC_15_041_mypy_strict_clean() -> None:
    """``mypy --strict`` must be clean across ``src/``."""
    import sys

    r = subprocess.run(
        [sys.executable, "-m", "mypy", "--strict", "src"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if "No module named mypy" in r.stderr:
        pytest.skip("mypy not installed in venv")
    assert r.returncode == 0, f"mypy failed:\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"


SHIPPED_PACKS = ("reference", "healthcare", "finance", "telco", "retail")


def test_TC_15_050_domain_isolated() -> None:
    """Core modules must not import industry-specific terms. Packs live at
    repo-root ``domains/`` and are naturally excluded because this iterates
    ``src/deep_agent/`` only; the loader module is allow-listed since its
    docstring references pack concepts."""
    forbidden = [r"\btelco\b", r"\bgep\b", r"\bfinance\b", r"\bhealthcare\b", r"\bphi\b"]
    core_roots = [REPO_ROOT / "src" / "deep_agent"]
    offenders: list[str] = []
    for root in core_roots:
        for py in root.rglob("*.py"):
            rel = py.relative_to(REPO_ROOT)
            text = py.read_text(encoding="utf-8").lower()
            for pat in forbidden:
                if re.search(pat, text):
                    offenders.append(f"{rel}: matched /{pat}/")
    assert not offenders, "core code leaked industry-specific terms:\n" + "\n".join(offenders)


def test_TC_15_051_core_does_not_read_domain_seeds_directly() -> None:
    """Core persistence/tools/agents/server must not read pack seed files
    directly - only ``ingestion`` does via the pack loader."""
    core_dirs = ["persistence", "tools", "agents", "server"]
    hits: list[str] = []
    forbidden_snippets = ("domain/seeds", "domain.seeds", "domains/")
    for sub in core_dirs:
        for py in (REPO_ROOT / "src" / "deep_agent" / sub).rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            for snippet in forbidden_snippets:
                if snippet in text:
                    hits.append(f"{py.relative_to(REPO_ROOT)}: {snippet}")
    assert not hits, f"core code referenced pack seeds directly: {hits}"


def test_TC_20_040_five_packs_shipped() -> None:
    """REQ-E-220/240: exactly five packs live under ``domains/``."""
    domains_root = REPO_ROOT / "domains"
    shipped = {p.name for p in domains_root.iterdir() if p.is_dir()}
    assert shipped == set(SHIPPED_PACKS), (
        f"expected {set(SHIPPED_PACKS)} under domains/, found {shipped}"
    )


@pytest.mark.parametrize("pack", SHIPPED_PACKS)
def test_TC_20_041_pack_has_required_files(pack: str) -> None:
    """REQ-E-221/241: each pack has pack.yaml, prompts.py, README, seeds."""
    pack_dir = REPO_ROOT / "domains" / pack
    assert (pack_dir / "pack.yaml").is_file()
    assert (pack_dir / "prompts.py").is_file()
    assert (pack_dir / "README.md").is_file()
    assert (pack_dir / "seeds" / "knowledge_base.json").is_file()
    assert (pack_dir / "seeds" / "knowledge_graph.json").is_file()
    assert (pack_dir / "seeds" / "operational").is_dir()


_CORE_COLLECTIONS = frozenset({
    "checkpoints", "checkpoint_writes", "long_term_memory", "chat_history",
    "llm_cache", "knowledge_base", "knowledge_graph", "stream_events",
    "feedback", "vfs_files", "plans", "fs.files", "fs.chunks",
})


@pytest.mark.parametrize("pack", SHIPPED_PACKS)
def test_TC_20_045_pack_collections_do_not_collide_with_core(pack: str) -> None:
    """Pack operational collections must not use names reserved by core."""
    import yaml

    pack_dir = REPO_ROOT / "domains" / pack
    meta = yaml.safe_load((pack_dir / "pack.yaml").read_text(encoding="utf-8"))
    collisions = set(meta["allow_list"]) & _CORE_COLLECTIONS
    assert not collisions, (
        f"{pack} pack.yaml:allow_list collides with core collections: {collisions}"
    )


@pytest.mark.parametrize("pack", SHIPPED_PACKS)
def test_TC_20_042_pack_allow_list_matches_seeds(pack: str) -> None:
    """REQ-E-222/241: pack.yaml allow_list == stems of seeds/operational/*.json."""
    import yaml

    pack_dir = REPO_ROOT / "domains" / pack
    meta = yaml.safe_load((pack_dir / "pack.yaml").read_text(encoding="utf-8"))
    declared = set(meta["allow_list"])
    on_disk = {p.stem for p in (pack_dir / "seeds" / "operational").glob("*.json")}
    assert declared == on_disk, f"{pack}: allow_list={declared} vs seeds={on_disk}"


_PACK_VOCAB: dict[str, tuple[str, ...]] = {
    "healthcare": ("patient", "clinical"),
    "finance": ("account", "transaction"),
    "telco": ("subscriber", "ticket"),
    "retail": ("order", "product"),
}


@pytest.mark.parametrize("pack", sorted(_PACK_VOCAB.keys()))
def test_TC_20_043_pack_prompts_reference_domain_vocab(pack: str) -> None:
    """REQ-E-223/242: each non-reference pack's prompts mention domain vocab."""
    prompts_path = REPO_ROOT / "domains" / pack / "prompts.py"
    text = prompts_path.read_text(encoding="utf-8").lower()
    anchors = _PACK_VOCAB[pack]
    assert any(a in text for a in anchors), (
        f"{pack}/prompts.py must mention at least one of {anchors}"
    )


def test_TC_20_044_reference_pack_present() -> None:
    """REQ-E-244: reference pack is at domains/reference with all pieces."""
    ref = REPO_ROOT / "domains" / "reference"
    assert (ref / "pack.yaml").is_file()
    assert (ref / "prompts.py").is_file()
    assert (ref / "seeds").is_dir()
    # The old in-tree domain package must be gone.
    assert not (REPO_ROOT / "src" / "deep_agent" / "domain").exists()
