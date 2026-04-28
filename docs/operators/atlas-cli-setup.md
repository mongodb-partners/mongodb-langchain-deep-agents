# Atlas CLI - one-shot cluster + indexes setup

Provision an Atlas cluster, load seed data, and create every Atlas Vector
Search / Search index the reference needs - without the UI.

## Prerequisites

```bash
brew install mongodb-atlas    # macOS (or: https://www.mongodb.com/docs/atlas/cli/stable/install/)
atlas auth login
```

## 1. Provision an M10 cluster

```bash
ATLAS_PROJECT_ID="$(atlas projects list --limit 1 -o json | jq -r '.results[0].id')"

atlas clusters create deep_agent \
  --projectId "$ATLAS_PROJECT_ID" \
  --provider AWS \
  --region US_EAST_1 \
  --tier M10 \
  --mdbVersion 8.0

atlas clusters connectionStrings describe deep_agent \
  --projectId "$ATLAS_PROJECT_ID" \
  -o json | jq -r '.standardSrv'
# → set this as MONGODB_URI in .env
```

## 2. Seed collections

```bash
export MONGODB_URI="mongodb+srv://<user>:<pass>@deep-agent.xxx.mongodb.net/"
uv run deep-agent seed
```

## 3. Indexes (idempotent)

```bash
uv run python -c "from deep_agent.persistence.indexes import ensure_indexes; ensure_indexes()"
```

This creates:

| Collection | Index | Shape |
|---|---|---|
| `knowledge_base` | `vector_index` | 1024-dim cosine + filter on `metadata.source` |
| `knowledge_base` | `search_index` | dynamic text index |
| `llm_cache` | `llm_cache_semantic_index` | 1024-dim cosine + `llm_string` filter |
| `long_term_memory` | `memory_semantic_index` | 1024-dim cosine |
| `chat_history` | `session_id_idx` | compound on `SessionId` |
| `vfs_files` | `vfs_thread_path_unique` | unique `(thread_id, path)` |
| `plans` | `plans_user_thread_unique` | unique `(user_id, thread_id)` |
| `stream_events` | `ts_ttl_idx` | TTL, 30 days |

## 4. Stream Processing Instance (optional)

```bash
atlas streams instances create deep_agent-sp \
  --projectId "$ATLAS_PROJECT_ID" \
  --provider AWS --region us-east-1 --tier SP30
# Register Kafka + Atlas connections (follow the SP instance URL)
mongosh "<SP-URI>" streaming/atlas_sp_pipeline.js
```
