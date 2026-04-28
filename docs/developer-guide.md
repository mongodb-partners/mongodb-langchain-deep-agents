# Developer Guide

## Setup

```bash
uv sync --extra dev
cp .env.example .env
```

## Layout

```
src/deep_agent/
├── agents/         # researcher subagent definition
├── backends/       # deepagents BackendProtocol adapter -> VirtualFilesystem
├── domain/         # industry-specific prompts + seeds (swappable)
├── ingestion/      # seed loader, change-stream worker, ASP helpers
├── middleware/     # custom AgentMiddleware (PlanPersistenceMiddleware)
├── persistence/    # MongoDB surfaces: saver, store, cache, indexes, vector/graph stores, plans
├── server/         # FastAPI app
├── tools/          # LangChain tools (KB + KG + web + fetch + safety-wrapped toolkit)
├── vfs/            # BlobStore protocol + GridFS + S3 backends
├── cli.py
├── config.py
├── evals.py
├── graph.py        # build_graph() via deepagents.create_deep_agent
└── models.py       # get_llm / get_embeddings / get_reranker

tests/
├── fixtures/       # evals_dataset.jsonl + other static fixtures
├── integration/    # gated on ATLAS_URI (6 tests)
└── unit/           # hermetic (181 tests)

scripts/            # operator helpers (e.g. create_evals_dataset.py)
streaming/          # Kafka + producer + ASP pipeline
docs/               # this directory (+ docs/operators/ runbooks)
```

## Everyday commands

```bash
uv run pytest                                    # unit suite
uv run ruff check src tests streaming/producer.py
uv run mypy --strict src
uv run deep-agent chat --once "hi" --user me     # smoke-test the graph
uv run deep-agent serve --port 8000 --reload     # FastAPI with hot reload
uv run langgraph dev                             # Studio playground
```

## Quality gates (enforced in CI)

- `ruff check` clean across `src`, `tests`, `streaming/producer.py`
- `mypy --strict src` clean
- `test_TC_15_050_domain_isolated` - no industry terms in core
- `test_TC_15_051_core_does_not_read_domain_seeds_directly`
- `test_TC_15_052_domain_swap_only_touches_one_directory`

All three structural gates live in `tests/unit/test_quality_gates.py` so
`uv run pytest` fails on regression.

## Adding a tool

1. Put the tool in `src/deep_agent/tools/<name>.py`, decorate with
   `@langchain_core.tools.tool`.
2. Wrap any expensive backing client in `@lru_cache(maxsize=1)` and expose a
   module-level indirection so tests can monkeypatch.
3. Bind it into the main agent or the researcher subagent.
4. Write unit tests that patch the backing store.

## Adding a middleware

1. Subclass `langchain.agents.middleware.AgentMiddleware` under
   `src/deep_agent/middleware/<name>.py`.
2. Implement one or more hooks - `before_model`, `after_model`,
   `wrap_model_call`, `before_agent`, `after_agent`. Hooks must return
   state-update dicts or `None`; never raise.
3. Wrap external side effects (MongoDB writes, HTTP calls) in
   exception handlers so middleware failures never fail the user turn.
   `PlanPersistenceMiddleware` logs + swallows `PyMongoError` as precedent.
4. Register the middleware in `build_graph()`'s `middleware=[...]` list.
5. Unit-test directly by constructing the middleware and calling its hook
   with a mock state dict and `runtime.config`. See
   `tests/unit/test_plan_middleware.py` for the pattern.

## Adding a VFS backend

1. Implement `BlobStore` (`put` / `get` / `delete`) in
   `src/deep_agent/vfs/<name>_backend.py`.
2. Add the branch in `vfs/__init__.py:get_vfs()`.
3. Add a `Literal` value to `Settings.vfs_backend`.
4. Parameterise the contract suite against the new backend.

## Switching LLM providers

`get_llm()` delegates to `init_chat_model(model_provider=..., ...)`. Flip via
env:

```bash
LLM_PROVIDER=openai
LLM_MODEL=gpt-4.1-mini
OPENAI_API_KEY=sk-...
```

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `ValueError: MONGODB_URI must enforce TLS` | Plain `mongodb://` without `tls=true`; set `ALLOW_INSECURE=true` in dev |
| `OperationFailure: ... index ... exists` | Benign; `_safe_create_search_index` swallows duplicate-index errors |
| `web_search` raises `ToolDisabledError` | `TAVILY_API_KEY` not set |
| Data tool returns `QUERY REFUSED` | Pipeline violates one of the four safety rules |
| `VfsQuotaExceededError` | File larger than `VFS_MAX_BYTES` (50 MiB default) |
| Deep-agent stops early | Hit `MAX_STEPS` bound; raise it or shorten prompts |
