# VFS Backends

The virtual filesystem is pluggable: blobs go to either GridFS (default) or
S3, selected by `VFS_BACKEND`. **Metadata always lives in MongoDB** so
listing / globbing / thread scoping work identically across backends.

| Layer | GridFS backend | S3 backend |
|---|---|---|
| Byte storage | `fs.files` / `fs.chunks` in the configured DB | `s3://<bucket>/<prefix>/<thread_id>/<path>` |
| Metadata | `vfs_files` collection | `vfs_files` collection |
| Listing / globbing | `vfs_files.find({thread_id})` + fnmatch | same |
| Auth | `MONGODB_URI` | IAM role |

## Why both backends

GridFS-only would be a weaker reference. Many production teams pattern on
"MongoDB for metadata, S3 for blobs"; shipping that split makes this repo a
genuine reference for that pattern. Metadata in MongoDB also preserves
listing semantics consistent across backends and keeps the coordination
plane in one place.

## Configuration

### GridFS (default)

No extra configuration. The backend attaches to the configured database and
uses `gridfs.GridFS(db)` directly.

```bash
VFS_BACKEND=gridfs
```

### S3

```bash
VFS_BACKEND=s3
VFS_S3_BUCKET=deep-agent-artifacts
VFS_S3_PREFIX=deep-agent
VFS_S3_REGION=us-east-1
```

The bucket must exist. `boto3` resolves credentials from the standard AWS
chain (env vars → shared credentials file → IAM role).

## Object layout (S3)

```
s3://<bucket>/<prefix>/<thread_id>/<path>
```

`thread_id` in the key naturally segments the namespace. Each object carries
`thread_id` as object metadata for debuggability.

## IAM policy (S3)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::deep-agent-artifacts/deep-agent/*"
    },
    {
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::deep-agent-artifacts",
      "Condition": {"StringLike": {"s3:prefix": "deep-agent/*"}}
    }
  ]
}
```

Do **not** grant `s3:ListBucket` at the bucket root - see
[security.md](security.md).

## Deepagents filesystem tools

Deepagents ships built-in `read_file` / `write_file` / `edit_file` / `ls` /
`glob` / `grep` tools; by default they store files in LangGraph state. This
repo wires a `mongo_backend_factory` into `create_deep_agent` so those tools
call into our `VirtualFilesystem` instead, and artifacts persist to MongoDB
(GridFS or S3). `thread_id` is read from the tool runtime's
`RunnableConfig.configurable` so each turn sees its own view.

```
deepagents built-in tools       BackendProtocol          VirtualFilesystem
  write_file("/notes.md")  ──▶  MongoVfsBackend.write ──▶ GridFS / S3 bytes
  read_file("/notes.md")   ──▶  MongoVfsBackend.read         + vfs_files metadata
```

See [mongodb-backend.md](mongodb-backend.md) for the adapter's full contract
(how `ls` builds directory entries, how `edit` preserves `created_at`, what
happens to binary files).

## Contract tests

Both backends implement `BlobStore` and are exercised against the same
`tests/unit/vfs_contract.py` suite:

- `TC-06-040` runs the contract against `GridFSBackend` (mongomock + gridfs shim).
- `TC-07-040` runs the contract against `S3Backend` (moto `mock_aws`).

If you add a future backend (Azure Blob, GCS, local disk), implement
`BlobStore` and parameterise the contract suite - no other tests should
need to change.

## Size limits

`VFS_MAX_BYTES` (default 50 MiB) is enforced at `VirtualFilesystem.write_file`
for both backends. Oversize writes raise `VfsQuotaExceededError`.

## Upsert semantics

Writing to an existing `(thread_id, path)`:

- **GridFS**: allocates a new ObjectId and deletes the old blob.
- **S3**: overwrites the key in place; the `locator` string is stable.

Both outcomes satisfy the contract. The metadata `updated_at` advances;
`created_at` is preserved.

## Choosing a backend

| Factor | GridFS | S3 |
|---|---|---|
| Zero external infrastructure | ✓ | - |
| Single-credential demo | ✓ | - |
| Large blobs at scale | OK | ✓ |
| Cross-region replication | via Atlas | via S3 replication |
| Operator familiarity | varies | high |

Default GridFS for the developer-experience story; flip to S3 in production.
