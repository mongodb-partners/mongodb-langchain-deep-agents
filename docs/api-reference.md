# API Reference

Three entry surfaces:

- [HTTP API](#http-api) - FastAPI with SSE streaming
- [CLI](#cli) - `deep-agent` command
- [Python API](#python-api) - factories and tools

## HTTP API

`create_app()` (`src/deep_agent/server/app.py`) returns the FastAPI instance.
Factory for uvicorn: `deep_agent.server.app:get_asgi_app`.

### `POST /chat`

Stream tokens for a research turn via SSE.

| Field | Type | Required | Description |
|---|---|---|---|
| `user_id` | string | yes | Scopes long-term memory + the auth boundary |
| `thread_id` | string | no | Defaults to `{user_id}:default` |
| `message` | string | yes | User request |

Response: `text/event-stream`, frames `token` / `done` / `error`.

Side effects:

- Appends the user message and final answer to `chat_history`
- Upserts the plan snapshot to `plans` at stream completion

`PyMongoError` on appends is logged and swallowed. Graph errors surface as
`event: error` SSE frames.

### `POST /feedback`

```json
{"run_id": "...", "score": 1.0, "comment": "...", "user_id": "..."}
```

Inserts into `feedback`; mirrors to LangSmith when `LANGSMITH_TRACING=true`.
Mirror failures are swallowed. 500 on `PyMongoError` during insert.

### `GET /health`

```json
{"mongo": "ok", "db": "deep_agent", "ts": "…"}
```

Never 5xx's on ping failure - reports `error: <ExceptionClassName>` instead.

## CLI

Entry point: `deep-agent` (`pyproject.toml` → `deep_agent.cli:main`).

```
deep-agent [-h] {chat,seed,serve} ...
```

### `deep-agent chat`

| Flag | Default |
|---|---|
| `--once MESSAGE` | _(none)_ |
| `--user USER_ID` | `demo-user` |
| `--thread THREAD_ID` | `cli-default` |

- Builds the graph (cached per process)
- Builds `MongoDBChatMessageHistory` keyed by `--thread`
- Invokes the graph; prints the last AI message content
- Appends user + AI messages to `chat_history` (swallow `PyMongoError`)
- Calls `persist_plan_snapshot` so the `plans` collection reflects the turn

REPL mode exits on `/quit`, `/exit`, or EOF.

### `deep-agent seed`

Runs `deep_agent.ingestion.seed.seed_all()` and prints the summary.

### `deep-agent serve`

| Flag | Default |
|---|---|
| `--host` | `0.0.0.0` |
| `--port` | `8000` |
| `--reload` | _(off)_ |

Boots FastAPI via uvicorn using the ASGI factory.

## Python API

### `deep_agent.graph`

- `build_graph() -> CompiledStateGraph` - main + researcher; binds
  `MongoDBSaver`, `MongoDBStore`, `mongo_backend_factory`, and
  `PlanPersistenceMiddleware`; installs the semantic cache once per process
- `build_graph_uncheckpointed() -> CompiledStateGraph` - same graph without
  persistence; used by unit tests

### `deep_agent.models`

- `get_llm() -> BaseChatModel`
- `get_embeddings() -> Embeddings` (asymmetric Voyage)
- `get_reranker() -> VoyageAIRerank`

### `deep_agent.persistence`

- `mongo.get_client() / get_db() / reset_for_tests()`
- `indexes.ensure_indexes()`
- `checkpointer.build_checkpointer() -> MongoDBSaver`
- `store.build_store() -> MongoDBStore`
- `store.build_namespace(user_id) -> ("user", user_id, "memories")`
- `chat_history.build_chat_history(session_id) -> MongoDBChatMessageHistory`
- `semantic_cache.install_semantic_cache() / is_installed()`
- `vector_store.build_vector_store() -> MongoDBAtlasVectorSearch`
- `graph_store.build_graph_store() -> MongoDBGraphStore`
- `plans.save_plan / load_plan / delete_plan` - direct upsert / load / delete
  on the `plans` collection
- `plans.persist_plan_snapshot(state, *, user_id, thread_id)` - turn-boundary
  helper retained as a safety net. `PlanPersistenceMiddleware` covers the
  mid-turn path; this helper is called by the CLI and `/chat` to cover the
  first-turn-after-resume case.
- `plans.PlanDoc / TodoItem`

### `deep_agent.backends`

- `mongo_backend_factory(runtime) -> MongoVfsBackend` - deepagents backend
  factory that reads `thread_id` from `runtime.config["configurable"]` and
  returns a `MongoVfsBackend` bound to that thread
- `MongoVfsBackend(vfs, thread_id)` - implements deepagents'
  `BackendProtocol` (`ls`, `read`, `write`, `edit`, `glob`, `grep`) on top of
  `VirtualFilesystem`. See [mongodb-backend.md](mongodb-backend.md).

### `deep_agent.middleware`

- `PlanPersistenceMiddleware()` - custom `AgentMiddleware` whose
  `after_model` hook upserts the current todo list (`state["todos"]`) into
  the `plans` collection. Dedupes on a snapshot key so identical states do
  not re-write. `PyMongoError` is logged and swallowed so the planning loop
  never dies on plan-collection unavailability.

### `deep_agent.vfs`

- `get_vfs() -> VirtualFilesystem` (selects backend from `VFS_BACKEND`)
- `VirtualFilesystem(backend, metadata, max_bytes)` with `read_file /
  write_file / delete_file / list_files / glob_files`
- `GridFSBackend(db, fs_factory=None)`
- `S3Backend(bucket, prefix, client)`
- `VfsMetadataStore(collection)`
- Exceptions: `VfsError`, `VfsFileNotFoundError`, `VfsQuotaExceededError`

### `deep_agent.tools`

LangChain `@tool`s:

- `knowledge_base_search(query, k=4, source=None)` - Atlas `$vectorSearch`
  with optional `pre_filter`, Voyage rerank
- `knowledge_base_hybrid_search(query)` - RRF hybrid + rerank
- `knowledge_graph_search(query)` - GraphRAG; sentinel on `OperationFailure`
- `web_search(query, max_results=5)` - Tavily; `ToolDisabledError` without key
- `fetch_and_cache(url, thread_id=None)` - HTTP → VFS → KB; dedupe by SHA-256
- `database_toolkit.get_data_tools()` - safety-wrapped `MongoDBDatabaseToolkit` tools

### `deep_agent.ingestion`

- `seed.seed_all / seed_knowledge_base / seed_knowledge_graph / seed_operational_data`
- `stream_worker.run_once / run_with_backoff / resume_token_path`
- `asp.default_pipeline_spec / register_pipeline / stop_pipeline`

### `deep_agent.evals`

- `run_evaluation(dataset_name, experiment_prefix="deep_agent")`
- `main([...])` - argparse CLI (`--dataset`, `--prefix`)

The starter dataset lives at `tests/fixtures/evals_dataset.jsonl` and is
uploaded via `scripts/create_evals_dataset.py`. See [evals.md](evals.md).

### `deep_agent.config`

- `get_settings() -> Settings`
- `Settings` - pydantic model; see [configuration.md](configuration.md)
