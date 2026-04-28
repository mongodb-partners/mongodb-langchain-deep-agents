# Security Model

## TLS enforcement

`Settings._enforce_tls` rejects any `MONGODB_URI` that is not
`mongodb+srv://` and does not contain `tls=true` or `ssl=true`. Override:
`ALLOW_INSECURE=true` (dev only).

## Secret redaction

`Settings.__repr__` / `__str__` emit no secrets. Connection errors in
`persistence/mongo.py:get_client` re-raise with the URI redacted.

## Per-user memory scoping

Every graph entrypoint threads `user_id` into the config. `MongoDBStore`
namespaces are `("user", user_id, "memories")` - users cannot read each
other's long-term memory. `POST /chat` validates `user_id` at the boundary
(HTTP 422 when missing).

## VFS thread scoping

Every metadata query in `VfsMetadataStore` carries `thread_id` as a top-level
filter. A thread cannot see another thread's files. The S3 backend encodes
`thread_id` into the object key; the GridFS backend stores `thread_id` in the
file metadata. `(thread_id, path)` is unique at the index level.

## Data-agent safety wrapper

`tools/database_toolkit.py` layers four protections on `MongoDBDatabaseToolkit`:

1. Underscore-prefixed collections refused.
2. Non-allow-listed collections refused.
3. Destructive stages (`$out` / `$merge` / `$function` / `$where` /
   `$accumulator`) and keywords (`drop` / `deleteMany` / etc.) refused.
4. Implicit `$limit: 1000` injected when missing.

Refusals return `"QUERY REFUSED: <reason>"` to the LLM so it can reroute.

`DATA_AGENT_MONGODB_URI` routes data-agent calls through a least-privilege
Atlas role (read-only on allow-listed collections). Defense in depth: the
wrapper blocks at the Python layer AND the role blocks at the DB layer.

The allow-list is now sourced per-pack from `pack.yaml:allow_list` (see
[domain-packs.md](domain-packs.md)). When deploying a pack against the
`deep_agent_dataagent` role, update the role's collection grants to match
the active pack's `allow_list` - e.g. `{patients, encounters, medications}`
for healthcare, `{accounts, transactions, customers}` for finance.

## RBAC

Four Atlas roles in [operators/rbac-example.md](operators/rbac-example.md):

| Role | Used by | Privileges |
|---|---|---|
| `deep_agent_app` | FastAPI/CLI/langgraph dev | Read/write app collections; no DDL |
| `deep_agent_dataagent` | Data agent | Read-only on `customers`, `orders`, `products` |
| `deep_agent_ingest` | Seed + stream worker | Insert on KB, KG, `stream_events`; change stream |
| `deep_agent_admin` | `ensure_indexes()` bootstrap | `dbAdmin` |

## VFS S3 IAM policy

When `VFS_BACKEND=s3`, scope the IAM policy to the prefix only. Do not allow
`s3:ListBucket` at the bucket root - a compromised runtime could enumerate
other tenants' prefixes. Example in [vfs-backends.md](vfs-backends.md).

## LangSmith & Voyage & Tavily keys

Treat all API keys as high-sensitivity secrets. Rotate; store in AWS Secrets
Manager / Vault. Per-environment LangSmith keys; never checked into source.
