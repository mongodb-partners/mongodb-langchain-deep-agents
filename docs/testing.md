# Testing

Two-tier suite: hermetic unit tests + an Atlas-gated integration tier.

## Quick reference

| Tier | Command | Requires |
|---|---|---|
| Unit | `uv run pytest` | Nothing - `mongomock`, `moto`, fakes |
| Integration | `ATLAS_URI=... uv run pytest -m integration` | Live Atlas cluster |
| Lint | `uv run ruff check src tests streaming/producer.py` | ruff |
| Type check | `uv run mypy --strict src` | mypy |

## pytest configuration

From `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = [
    "integration: requires ATLAS_URI; skipped by default",
    "slow: long-running test",
]
addopts = "-m 'not integration' --strict-markers -ra"
```

Running `pytest` excludes the integration marker by default.

## Unit tier

Location: `tests/unit/`. Fixtures:

- Autouse env pinning in `tests/unit/conftest.py` - unit tests stay
  hermetic regardless of the local `.env`.
- `mongomock_client` for Mongo-backed code.
- `moto.mock_aws` for S3 code (`tests/unit/test_vfs_s3.py`).
- Deterministic `_FakeEmbedder` in shared conftest.

## Quality gates

Three structural tests in `tests/unit/test_quality_gates.py`:

- `test_TC_15_040_ruff_clean`
- `test_TC_15_041_mypy_strict_clean`
- `test_TC_15_050_domain_isolated` - greps core for forbidden industry terms
- `test_TC_15_051_core_does_not_read_domain_seeds_directly`
- `test_TC_15_052_domain_swap_only_touches_one_directory`

These run in the unit tier so a failing gate fails `uv run pytest`.

## VFS contract

`tests/unit/vfs_contract.py` defines assertions every backend must satisfy
(round trip, thread scoping, upsert, size limit, glob). Sub-phases 05 / 06 /
07 run the same contract against three different backends (dict stub, GridFS
shim via mongomock, S3 under moto). Adding a future backend means adding one
test file that parameterises the fixture.

## Integration tier

Location: `tests/integration/`. Every test is marked `pytest.mark.integration`
and each fixture calls `pytest.skip` when its env var is unset, so
`uv run pytest -m integration` is a clean no-op without live infrastructure.

| File | Test IDs | Env vars |
|---|---|---|
| `test_e2e.py` | `TC-INT-010` checkpoint resume, `TC-INT-020` plan round-trip, `TC-INT-030` LangSmith trace | `ATLAS_URI`; `LANGSMITH_API_KEY` for the trace test |
| `test_vfs_backends.py` | `TC-INT-040` GridFS contract, `TC-INT-050` S3 contract | `ATLAS_URI`; `VFS_S3_BUCKET` for the S3 case |
| `test_research_turn.py` | `TC-INT-060` full research flow | `ATLAS_URI`, `VOYAGE_API_KEY`, `TAVILY_API_KEY` (or the tool raises `ToolDisabledError` - test exercises the KB-only path) |

Each test calls `ensure_indexes()` at setup so you do not bootstrap DDL
separately, and each creates a uniquely-named database or prefix so parallel
runs do not collide. Cleanup runs in `finally` blocks.

Minimum command:

```bash
ATLAS_URI="mongodb+srv://..." VOYAGE_API_KEY=pa-... uv run pytest -m integration
```

Full coverage including streaming also exports `ASP_URI` and
`KAFKA_BOOTSTRAP_SERVERS`.

## Evals dataset + uploader

`tests/fixtures/evals_dataset.jsonl` is the starter Q&A set; the uploader at
`scripts/create_evals_dataset.py` is exercised by four unit tests
(`tests/unit/test_evals_dataset.py`). See [evals.md](evals.md).
