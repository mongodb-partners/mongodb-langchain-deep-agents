# Getting Started

From clean checkout to a working research turn in about ten minutes.

## Prerequisites

- Python 3.11 or later
- [`uv`](https://github.com/astral-sh/uv)
- Atlas cluster at tier **M10 or higher** (Vector Search dedicated nodes)
- [Voyage AI API key](https://docs.voyageai.com/docs/api-key-and-installation)
- AWS credentials with Bedrock access (default LLM)
- [Tavily API key](https://tavily.com) (for web research)
- Optional: S3 bucket + IAM creds if you want to run the S3 VFS backend

## 1. Install

```bash
git clone <this-repo>
cd mongodb-langchain-deep-agents
uv sync --extra dev
```

## 2. Configure

```bash
cp .env.example .env
```

Required keys:

```bash
MONGODB_URI=mongodb+srv://USER:PASS@cluster.mongodb.net/?retryWrites=true&w=majority
MONGODB_DB=deep_agent
VOYAGE_API_KEY=pa-...
TAVILY_API_KEY=tvly-...
```

See [configuration.md](configuration.md) for the full list.

## 3. Create indexes

```bash
uv run python -c "from deep_agent.persistence.indexes import ensure_indexes; ensure_indexes()"
```

Idempotent; Atlas Vector Search indexes take ~1 minute to become queryable.

## 4. Seed the knowledge base + operational data

```bash
uv run deep-agent seed
```

Fixtures under `src/deep_agent/domain/seeds/` are industry-neutral by
default. Swap them to retarget (see [domain-adaptation.md](domain-adaptation.md)).

## 5. Run a research turn

```bash
uv run deep-agent chat --user alice --once "Research MongoDB Atlas Vector Search and summarize the trade-offs."
```

The main agent will typically: write a todo list → delegate to the
`researcher` subagent (which searches the KB, then the web if needed) →
compose the final answer → save the plan to MongoDB.

Or start the HTTP server:

```bash
uv run deep-agent serve --port 8000
```

Endpoints:

- `POST /chat` - SSE stream (required `user_id`, optional `thread_id`)
- `POST /feedback` - persist user scores (optionally mirrored to LangSmith)
- `GET /health` - pings MongoDB

Or open LangGraph Studio:

```bash
uv run langgraph dev
```

## 6. Run the test suite

```bash
uv run pytest
```

181 hermetic unit tests. Integration tier (requires `ATLAS_URI`) lives under
`tests/integration/`; see [testing.md](testing.md) for the full matrix.

## 7. Upload the starter eval dataset (optional)

```bash
uv run python scripts/create_evals_dataset.py
uv run python -m deep_agent.evals --dataset deep_agent_starter
```

The uploader is idempotent; re-running it tops up the LangSmith dataset
with any new rows in the local fixture. See [evals.md](evals.md).

## What next

- [Architecture](architecture.md)
- [Configuration](configuration.md)
- [VFS Backends](vfs-backends.md) - GridFS vs S3
- [MongoDB Backend](mongodb-backend.md) - how the filesystem tools persist
- [Streaming](streaming.md) - Kafka + Atlas Stream Processing
- [Evals](evals.md) - starter dataset + custom evaluators
- [Domain Adaptation](domain-adaptation.md)
