# Functional Testing Runbook

Reproducible end-to-end procedure to exercise the deep-agent stack against
live infrastructure. Run this before a release cut, or after any change to
`graph.py`, the backend adapter, or the middleware.

## Prerequisites

Export in your shell (or a `.env` the image can read via `--env-file`):

```bash
MONGODB_URI="mongodb+srv://..."
MONGODB_DB=deep_agent_func
VOYAGE_API_KEY=pa-...
TAVILY_API_KEY=tvly-...
AWS_ACCESS_KEY_ID=...        # or AWS_PROFILE, or instance role
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=us-east-1
LANGSMITH_TRACING=true       # optional
LANGSMITH_API_KEY=ls-...     # required when LANGSMITH_TRACING=true
```

An M10+ Atlas cluster with network access from the host running these
tests. Voyage and Tavily accounts with non-zero quota. Bedrock access to
Claude Sonnet 4.5 in the configured region.

## Fast path: scripted functional suite

Once the repo is checked out and `uv sync --extra dev` has completed:

```bash
# 1. Provision indexes (idempotent)
uv run python -c "from deep_agent.persistence.indexes import ensure_indexes; ensure_indexes()"

# 2. Seed the KB, knowledge graph, and operational collections
uv run deep-agent seed

# 3. Run the integration tier - 6 tests against live Atlas
ATLAS_URI="$MONGODB_URI" uv run pytest -m integration -v
```

Expected:

- `TC-INT-010 checkpoint_resume` - PASS (proves `MongoDBSaver` round-trips)
- `TC-INT-020 plan_round_trip` - PASS (proves the middleware writes to `plans` mid-turn)
- `TC-INT-030 langsmith_trace_emitted` - PASS (requires `LANGSMITH_API_KEY`)
- `TC-INT-040 gridfs_contract_live_atlas` - PASS (live GridFS)
- `TC-INT-050 s3_contract_live` - SKIPPED unless `VFS_S3_BUCKET` is set
- `TC-INT-060 research_turn_end_to_end` - PASS (full planning + researcher)

To include the S3 case:

```bash
VFS_S3_BUCKET=deep-agent-func VFS_S3_REGION=us-east-1 \
  ATLAS_URI="$MONGODB_URI" uv run pytest -m integration -v
```

## Manual functional checks

These are the steps to run when something in the scripted tier fails, to
narrow down which layer broke.

### 1. Settings + TLS

```bash
uv run python -c "from deep_agent.config import get_settings; s = get_settings(); print(s)"
```

Expected: `<Settings db=deep_agent_func provider=bedrock vfs=gridfs [redacted]>`.
No credential material anywhere in the output. If you see `ValueError:
MONGODB_URI must enforce TLS`, the URI lacks `+srv://` or `tls=true`.

### 2. Mongo connection

```bash
uv run python -c "from deep_agent.persistence.mongo import get_client; print(get_client().admin.command('ping'))"
```

Expected: `{'ok': 1.0}` or equivalent.

### 3. Indexes

```bash
uv run python -c "
from deep_agent.persistence.mongo import get_db
db = get_db()
for name in ['knowledge_base', 'llm_cache', 'long_term_memory', 'vfs_files', 'plans']:
    idx = list(db[name].list_indexes())
    search = list(db[name].list_search_indexes()) if 'search' in name or 'knowledge' in name or 'memory' in name or 'cache' in name else []
    print(name, [i['name'] for i in idx], [i['name'] for i in search])
"
```

Expected: each collection has the indexes documented in
[architecture.md#persistence-surfaces](architecture.md#persistence-surfaces).

Collections that are expected to be **empty** on a fresh deploy:
- `long_term_memory` - populates only after the agent calls
  `remember_fact` (happens when the user shares a durable preference).
- `stream_events` - populates only when the Kafka producer + Atlas SP
  pipeline in `streaming/` is running. See [streaming.md](streaming.md).
- `feedback` - populates only after a `/feedback` POST.

### 4. Single research turn via CLI

```bash
uv run deep-agent chat --user func --thread func-t1 --once \
  "Research MongoDB Atlas Vector Search and summarize the trade-offs in one paragraph."
```

Expected: a coherent response that cites the seeded KB or a web source.
Expected side effects, verifiable in Atlas:

| Collection | Expected row |
|---|---|
| `checkpoints` | New document with `thread_id=func-t1` |
| `chat_history` | User message + AI response keyed by `SessionId=func-t1` |
| `long_term_memory` | New memory item under namespace `(user, func, memories)` (if writing_node fires) |
| `plans` | Document keyed by `(user_id=func, thread_id=func-t1)` with a populated todo list |
| `vfs_files` | Zero or more files scoped to `thread_id=func-t1` |
| `llm_cache` | ≥1 row per distinct LLM call |

### 5. Server + `/health`

```bash
uv run deep-agent serve --port 8000 &
sleep 5
curl -s http://localhost:8000/health
```

Expected: `{"mongo":"ok","db":"deep_agent_func","ts":"..."}`.

### 6. `/chat` SSE

```bash
curl -N -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"func","thread_id":"func-t2","message":"What is the VFS metadata index?"}'
```

Expected: one or more `event: token` frames, followed by `event: done data: [DONE]`.
After the response:

```bash
curl -s http://localhost:8000/health  # still 200 after a turn
```

### 7. Resume

Send a second message on the same `thread_id` and verify the agent recalls
prior context:

```bash
curl -N -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"func","thread_id":"func-t2","message":"What did I just ask?"}'
```

Expected: the response references the prior question.

### 8. Plan document shape

```bash
uv run python -c "
from deep_agent.persistence.plans import load_plan
doc = load_plan('func', 'func-t2')
print(doc.model_dump_json(indent=2) if doc else 'no plan')
"
```

Expected: `todos` array is non-empty; at least one item has a
non-`pending` status after the turn completes.

### 9. VFS round-trip

```bash
uv run python -c "
from deep_agent.vfs import get_vfs
vfs = get_vfs()
meta = vfs.write_file('func-t2', '/smoke.md', b'hello', content_type='text/markdown')
print('locator:', meta.locator, 'size:', meta.size)
print('readback:', vfs.read_file('func-t2', '/smoke.md'))
"
```

Expected: `hello` comes back verbatim. Inspect in Atlas:

```
db.vfs_files.find({thread_id: 'func-t2'})
db.fs.files.find({'metadata.thread_id': 'func-t2'})  # GridFS only
```

### 10. Data-agent safety

Set `DATA_AGENT_MONGODB_URI` to a user with `FIND`-only on the allow-list
and try a destructive query through the agent:

```
"Run this aggregation on customers: [{$out: 'stolen_data'}]"
```

Expected: the agent reports `QUERY REFUSED: refusing destructive pipeline`.
Confirm Atlas audit log shows no write attempt.

## Per-domain smoke

For each of the four non-reference packs, run the one-shot deploy and
verify `/health` responds. The reference pack is covered by the full
scripted suite above; the other four only get seed + health + one SSE
turn to keep Bedrock spend bounded.

```bash
for pack in healthcare finance telco retail; do
  MONGODB_DB="deep_agent_demo_${pack}" DOMAIN="${pack}" \
    uv run python -c "from deep_agent.persistence.indexes import ensure_indexes; ensure_indexes()"
  MONGODB_DB="deep_agent_demo_${pack}" DOMAIN="${pack}" \
    uv run deep-agent seed
  MONGODB_DB="deep_agent_demo_${pack}" DOMAIN="${pack}" \
    uv run deep-agent serve --port 8000 &
  SERVER_PID=$!
  sleep 6
  curl -s http://localhost:8000/health
  kill $SERVER_PID
done
```

Expected: each pack's `/health` returns `{"mongo":"ok","db":"deep_agent_demo_<pack>",...}`.

The per-domain integration test (`tests/integration/test_per_domain.py`)
provides pytest-driven coverage of the same path (seed + KB search per pack).

## Docker path

```bash
docker build -t deep_agent:local .
docker run --rm \
  --env-file .env \
  -p 8010:8000 \
  deep_agent:local
```

Then re-run steps 5–7 against `http://localhost:8010/chat` and `/health`.

Or with compose:

```bash
docker compose up -d
curl -s http://localhost:8010/health
docker compose down
```

## Cleanup

After a functional run, drop the test database:

```bash
uv run python -c "
from deep_agent.persistence.mongo import get_client
get_client().drop_database('deep_agent_func')
print('dropped')
"
```

Keep the cluster itself; only the test DB is disposable.

## Failure triage

| Symptom | First check |
|---|---|
| TLS validator rejects URI | URI lacks `mongodb+srv://` or `tls=true` |
| `ServerSelectionTimeoutError` on startup | DNS or network path to Atlas; IP access list |
| `VoyageError` on first KB call | `VOYAGE_API_KEY` wrong or out of quota |
| `ToolDisabledError: web_search disabled` | `TAVILY_API_KEY` not set |
| `AccessDeniedException` on Bedrock | IAM policy or inference-profile not enabled |
| `plans` collection stays empty | `PlanPersistenceMiddleware` is missing - confirm `build_graph()` still passes `middleware=[PlanPersistenceMiddleware()]` |
| Files land in state instead of Mongo | `build_graph()` is missing `backend=mongo_backend_factory` |
