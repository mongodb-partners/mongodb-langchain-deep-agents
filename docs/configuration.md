# Configuration

All runtime configuration is centralised in `Settings`
(`src/deep_agent/config.py`). Fields read from environment variables, `.env`,
or defaults in that order. `get_settings()` caches the resolved instance.

## Environment variables

| Variable | Required | Default | Notes |
|---|---|---|---|
| `MONGODB_URI` | yes | - | Must be `mongodb+srv://` or include `tls=true` |
| `MONGODB_DB` | no | `deep_agent` | |
| `DATA_AGENT_MONGODB_URI` | no | falls back to `MONGODB_URI` | Least-privilege URI for the data agent |
| `LLM_PROVIDER` | no | `bedrock` | Any `init_chat_model` provider |
| `LLM_MODEL` | no | `global.anthropic.claude-sonnet-4-6` | Default chosen for Bedrock subagent compatibility - Sonnet 4.5 has a known interaction with deepagents subagents where the `task` tool's tool_use/tool_result pairing trips Bedrock's strict validator; Sonnet 4.6 handles that cleanly. |
| `AWS_DEFAULT_REGION` | no | `us-east-1` | Used when `LLM_PROVIDER=bedrock` |
| `VOYAGE_API_KEY` | yes | - | |
| `VOYAGE_DOCUMENT_MODEL` | no | `voyage-4` | High-capacity model used for ingestion |
| `VOYAGE_QUERY_MODEL` | no | `voyage-4-lite` | Latency-optimised model used for queries |
| `VOYAGE_DIMENSIONS` | no | `1024` | Must match the vector-index `numDimensions` |
| `VOYAGE_RERANK_MODEL` | no | `rerank-2.5` | |
| `VOYAGE_BASE_URL` | no | _(unset)_ | Gateway URL (e.g. MongoDB AI Gateway) |
| `TAVILY_API_KEY` | research path | - | Required by `web_search`; absent → tool disabled |
| `VFS_BACKEND` | no | `gridfs` | `gridfs` or `s3` |
| `VFS_MAX_BYTES` | no | `52428800` (50 MiB) | Per-file cap |
| `VFS_S3_BUCKET` | when S3 | - | Required when `VFS_BACKEND=s3` |
| `VFS_S3_PREFIX` | no | `deep-agent` | S3 key prefix |
| `VFS_S3_REGION` | no | _(unset)_ | Inherits boto3 default chain |
| `LANGSMITH_TRACING` | no | `false` | When true, `/feedback` mirrors to LangSmith |
| `LANGSMITH_API_KEY` | when tracing | - | |
| `LANGSMITH_PROJECT` | no | `deep_agent` | |
| `SEMANTIC_CACHE_THRESHOLD` | no | `0.9` | Cosine similarity threshold for cache hits |
| `MAX_STEPS` | no | `32` | Deep-agent recursion/step bound |
| `ALLOW_INSECURE` | no | `false` | Bypass the TLS check (dev only) |
| `DOMAIN` | no | `reference` | Active domain pack (see [domain-packs.md](domain-packs.md)). Rejects path separators and `..`. |
| `DOMAINS_ROOT` | no | `<repo>/domains` | Directory containing domain packs |

Unit tests pin this set via an autouse fixture in `tests/unit/conftest.py`.

### Stream-worker state

Resume-token file location (`src/deep_agent/ingestion/stream_worker.py`):

1. `DEEP_AGENT_STATE_DIR` - explicit override
2. `XDG_STATE_HOME/deep_agent`
3. `~/.deep_agent`

## Collection names

Override via attribute on `Settings` (not env vars today).

| Attribute | Default |
|---|---|
| `checkpoints_collection` | `checkpoints` |
| `checkpoint_writes_collection` | `checkpoint_writes` |
| `long_term_memory_collection` | `long_term_memory` |
| `chat_history_collection` | `chat_history` |
| `llm_cache_collection` | `llm_cache` |
| `knowledge_base_collection` | `knowledge_base` |
| `knowledge_graph_collection` | `knowledge_graph` |
| `stream_events_collection` | `stream_events` |
| `feedback_collection` | `feedback` |
| `vfs_files_collection` | `vfs_files` |
| `plans_collection` | `plans` |

## Index names

| Attribute | Default | Type |
|---|---|---|
| `knowledge_base_vector_index` | `vector_index` | vectorSearch + `metadata.source` filter |
| `knowledge_base_search_index` | `search_index` | Atlas `$search` dynamic |
| `llm_cache_vector_index` | `llm_cache_semantic_index` | vector + `llm_string` filter |
| `long_term_memory_vector_index` | `memory_semantic_index` | vector |

## TLS enforcement

`Settings._enforce_tls` rejects any `MONGODB_URI` that does not start with
`mongodb+srv://` and does not contain `tls=true`/`ssl=true`. `ALLOW_INSECURE=true`
is the dev escape hatch.

## Secret redaction

`__repr__` / `__str__` return
`<Settings db=<name> provider=<name> vfs=<backend> [redacted]>`. No secret
material is ever interpolated.
