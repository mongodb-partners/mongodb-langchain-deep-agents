# Architecture

This document explains the shape of the system: the deep-agent planning loop,
the researcher subagent, the pluggable VFS, and how MongoDB backs every
persistent surface.

## System context

`mongodb-langchain-deep-agents` is a **planning-style** reference. The main
agent maintains a todo list, delegates sub-tasks to a researcher subagent via
the `task` tool, and writes long artifacts to a virtual filesystem. Every
persistent surface (checkpoints, cross-thread memory, chat history, semantic
cache, knowledge base, knowledge graph, VFS metadata, plans) lives in MongoDB
Atlas; VFS blobs live in either GridFS or S3.

Companion to `mongodb-langchain-agentic-ai` which demonstrates **routing**
(supervisor + four specialists) - this repo showcases the complementary
pattern.

```
                 ┌────────────────────────────┐
                 │  CLI / FastAPI / LG Studio │
                 └──────────────┬─────────────┘
                                │
                                ▼
                     ┌────────────────────┐
                     │  build_graph()     │
                     │  deepagents 0.5.x  │
                     │  main + researcher │
                     └──────┬─────────────┘
                            │
   ┌────────────────────────┼──────────────────────────┐
   │                        │                          │
   ▼                        ▼                          ▼
┌──────────┐     ┌────────────────────┐       ┌──────────────────┐
│ Bedrock  │     │  Voyage embeddings │       │  MongoDB Atlas   │
│ Claude   │     │  + rerank-2.5      │       │  + GridFS / S3   │
└──────────┘     └────────────────────┘       └──────────────────┘
```

## Planning loop

The main agent's tool belt:

- `write_todos` - built-in deepagents planning tool. `PlanPersistenceMiddleware`
  intercepts every model response and upserts the current todo list into
  MongoDB's `plans` collection mid-turn.
- `read_file` / `write_file` / `edit_file` / `ls` / `glob` / `grep` - built-in
  deepagents filesystem tools, routed through our `VirtualFilesystem` by the
  `mongo_backend_factory` adapter. Artifacts land in MongoDB (GridFS or S3),
  not LangGraph state.
- `task("researcher", ...)` - delegates a focused sub-question to the
  researcher subagent
- `knowledge_base_search`, `knowledge_base_hybrid_search`,
  `knowledge_graph_search` - MongoDB Atlas Vector Search + RRF hybrid + GraphRAG
- `fetch_and_cache` - download a URL, write raw HTML to VFS, ingest chunks
  into the knowledge base
- safety-wrapped `MongoDBDatabaseToolkit` tools for NL → MQL over operational
  collections

The researcher subagent binds: `web_search` (Tavily), `fetch_and_cache`, and
all three retrieval tools.

## Shape of a research turn

```
POST /chat {user_id, thread_id, message}
      │
      ▼
  build_graph()  (cached)
      │
      ▼
  Main agent writes todos
      │                 (after_model hook)
      └──▶ PlanPersistenceMiddleware ──▶ plans (MongoDB)
      │
      ▼
  Main agent calls task("researcher", "sub-question")
      │
      ▼
  Researcher loop:
     kb/kg search ──▶ knowledge_base / knowledge_graph
     web_search    ──▶ Tavily
     fetch_and_cache ──▶ VFS (GridFS or S3) + knowledge_base
      │
      ▼
  Main agent writes files (write_file / edit_file)
      │
      └──▶ mongo_backend_factory ──▶ VirtualFilesystem ──▶ GridFS or S3
                                                           + vfs_files metadata
      │
  Main agent composes final answer
      │
      ▼
  Semantic cache consulted on every LLM call ──▶ llm_cache
  MongoDBSaver commits every super-step ──▶ checkpoints / checkpoint_writes
```

## Persistence surfaces

| Surface | Class | Collection(s) | Index |
|---|---|---|---|
| Short-term checkpoints | `MongoDBSaver` | `checkpoints`, `checkpoint_writes` | managed by MongoDBSaver |
| Cross-thread memory | `MongoDBStore` | `long_term_memory` | `memory_semantic_index` (1024-dim cosine) |
| Conversation log | `MongoDBChatMessageHistory` | `chat_history` | `SessionId` compound |
| LLM cache | `MongoDBAtlasSemanticCache` | `llm_cache` | `llm_cache_semantic_index` (vector + `llm_string` filter) |
| Vector KB | `MongoDBAtlasVectorSearch` | `knowledge_base` | `vector_index` + filterable `metadata.source` |
| Lexical KB | Atlas `$search` | `knowledge_base` | `search_index` (dynamic) |
| Knowledge graph | `MongoDBGraphStore` | `knowledge_graph` | managed by langchain-mongodb |
| VFS metadata | `VfsMetadataStore` | `vfs_files` | unique `(thread_id, path)` |
| VFS blobs (GridFS) | `gridfs.GridFS` | `fs.files`, `fs.chunks` | default GridFS indexes |
| Plans (todo lists) | `persistence/plans.py` | `plans` | unique `(user_id, thread_id)` |
| Stream sink | change stream | `stream_events` | TTL 30d on `ts` |
| Feedback | plain insert | `feedback` | - |

`ensure_indexes()` (`src/deep_agent/persistence/indexes.py`) creates every
index idempotently.

## VFS abstraction

Pluggable `BlobStore` protocol with two backends; metadata always in MongoDB
regardless of backend. Selected by `VFS_BACKEND` (`gridfs` default, `s3`
alternative). See [vfs-backends.md](vfs-backends.md) for the full story.

```
VirtualFilesystem
  ├── backend: GridFSBackend | S3Backend   (byte storage)
  └── metadata: VfsMetadataStore            (coordination plane, always MongoDB)
```

Deepagents' built-in `read_file`/`write_file`/`edit_file`/`ls`/`glob`/`grep`
tools speak a `BackendProtocol` contract (absolute paths, line-addressable
reads, structured result dataclasses). The `mongo_backend_factory` adapter in
`deep_agent.backends.mongo_backend` translates those calls into
`VirtualFilesystem` operations and carries `thread_id` from the tool runtime's
`RunnableConfig.configurable`. See [mongodb-backend.md](mongodb-backend.md).

## Plan persistence

Deep-agent plans (todo lists) are upserted into MongoDB mid-turn by
`PlanPersistenceMiddleware` (`deep_agent.middleware.plan`), a custom
`AgentMiddleware` whose `after_model` hook reads `state["todos"]` after every
model response. When the snapshot key
(`id`, `text/content`, `status`) differs from the previous call for the same
`(user_id, thread_id)`, the middleware calls `save_plan` to upsert the
document; unchanged states are no-ops. `persist_plan_snapshot` remains
available at turn boundaries (CLI + `/chat`) as a safety net for the
first-turn-after-resume case where the middleware's in-process snapshot is
empty.

## Invariants

Enforced structurally and by tests:

1. **TLS required**: `Settings._enforce_tls` rejects non-TLS URIs unless
   `ALLOW_INSECURE=true`.
2. **Per-user memory**: `MongoDBStore.search` namespace is always
   `("user", user_id, "memories")`.
3. **VFS thread scoping**: listings for a thread contain only that thread's
   files.
4. **Safety wrapper**: destructive pipeline stages never reach the database.
5. **Domain isolation**: core modules never read pack seeds directly; all
   pack content is reached via the loader in `src/deep_agent/domain_pack.py`.
   See [domain-packs.md](domain-packs.md) for the pack system.
6. **Chat resilience**: a `PyMongoError` on chat-history appends never 5xx's
   the `/chat` endpoint.
