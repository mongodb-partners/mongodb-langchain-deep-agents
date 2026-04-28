# Deploying Deep Agents

One script — [`scripts/deploy.sh`](../scripts/deploy.sh) — covers every
supported deployment shape: a single domain pack via Docker, all five packs
via Docker, or a staging push to Kanopy via Drone. The goal is
zero manual configuration beyond `.env`.

If anything goes wrong mid-deploy, the script tears down the Docker stack
so a retry starts clean. Preflight checks fail fast when `.env` has
placeholder values or the Docker tooling is missing.

## Prerequisites

| Requirement | Why | Install |
|---|---|---|
| `docker` + `docker compose` v2 | Builds + runs the stack | [Docker Engine](https://docs.docker.com/engine/install/) |
| `curl` | Health-check probing | OS package manager |
| MongoDB Atlas cluster | Every stateful surface (checkpoints, memory, VFS metadata, etc.) | M10+ recommended for Vector Search dedicated nodes |
| Voyage AI key | Embeddings + rerank | <https://www.voyageai.com> |
| AWS credentials with Bedrock access | LLM (Claude Opus 4.7) | Set `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` in `.env` |
| Tavily API key (optional) | `web_search` tool in the researcher subagent | Omit to keep the subagent KB-only |
| `kubectl` + `kanopy-oidc` (Kanopy only) | staging deploys via Drone | [kanopy-oidc releases](https://github.com/kanopy-platform/kanopy-oidc/releases) |

## `.env` setup

```bash
cp .env.example .env
$EDITOR .env
```

Required:

```bash
MONGODB_URI=mongodb+srv://USER:PASS@CLUSTER.mongodb.net/?retryWrites=true&w=majority
VOYAGE_API_KEY=pa-...
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
```

Recommended (these are the exact knobs this reference deployment depends on):

```bash
LLM_PROVIDER=bedrock
LLM_MODEL=global.anthropic.claude-opus-4-7
AWS_DEFAULT_REGION=us-east-1
MAX_HOPS=80
MAX_TOKENS=32000
```

> **Why Opus 4.7?** Sonnet 4.6 and Opus 4.5 each exhibit distinct
> failure modes on the multi-step planner loop (orphan `tool_use` blocks,
> infinite tool-argument retries). Opus 4.7 is the verified-stable model
> for this stack.

## Docker: single domain

```bash
scripts/deploy.sh finance
```

Does the following in order:

1. **Preflight**: `.env` exists with non-placeholder `MONGODB_URI` + `VOYAGE_API_KEY`; Docker + curl on PATH.
2. **Build** images (skip with `NO_BUILD=1`).
3. Export `DOMAIN=finance` and `MONGODB_DB=deep_agents_finance`.
4. `docker compose up -d` (backend + frontend; skip UI with `NO_FRONTEND=1`).
5. Wait up to `TIMEOUT=180`s for `GET /health` to return 200.
6. Seed the pack: `deep-agent --domain finance seed`.
7. Print URLs and a quick curl test.

On failure between steps 2 and 6 the compose stack is torn down so the
next run starts clean.

Available packs (one per directory under `domains/`):
`reference`, `healthcare`, `finance`, `retail`, `telco`.

## Docker: all domains

```bash
scripts/deploy.sh --all
```

Same preflight + build + start as single-domain mode, but seeds every pack
into its own database (`deep_agents_reference`, `deep_agents_healthcare`,
etc.). The backend routes per-request via the `X-Domain` header, so one
container serves all five packs. Seeding is iterative; one pack's failure
is reported at the end without aborting the others.

This is the **default deployment** for demos and the reference experience.

## Kanopy / staging

`.drone.yml` at the repo root drives a two-phase pipeline:

- **Build**: `plugins/kaniko-ecr` → `maap/${DRONE_REPO_NAME}/backend` and `.../frontend` tags `git-<sha>` + `latest`.
- **Deploy**: `public.ecr.aws/kanopy/drone-helm:v3` → `mongodb/web-app` chart 4.25.0 to namespace `maap`, two Helm releases:

| Release | Host | Resource limits |
|---|---|---|
| `mongodb-langchain-deep-agents-backend` | `mongodb-langchain-deep-agents-api.maap.staging.corp.mongodb.com` | 2000m / 4Gi |
| `mongodb-langchain-deep-agents-frontend` | `mongodb-langchain-deep-agents.maap.staging.corp.mongodb.com` | 1000m / 512Mi |

### One-time cluster setup

1. Install `kanopy-oidc` and authenticate:
   ```bash
   kanopy-oidc kube setup staging > ~/.kube/config.staging
   export KUBECONFIG=~/.kube/config.staging
   kanopy-oidc kube login
   kubectl config set-context --current --namespace=maap
   ```

2. Create the shared K8s secret (one object; every required env var points to it):
   ```bash
   kubectl -n maap create secret generic mongodb-langchain-deep-agents-secrets \
     --from-literal=MONGODB_URI='<atlas-uri>' \
     --from-literal=VOYAGE_API_KEY='<voyage-key>' \
     --from-literal=TAVILY_API_KEY='<tavily-key>' \
     --from-literal=AWS_ACCESS_KEY_ID='<aws-key>' \
     --from-literal=AWS_SECRET_ACCESS_KEY='<aws-secret>' \
     --from-literal=LANGSMITH_API_KEY='<langsmith-key>'
   ```
   Single-quote every value — `+`, `/`, and `&` in MongoDB URIs and AWS
   secrets get mangled by the shell otherwise.

3. Activate the repo in Drone and add three secrets under
   **repo → Settings → Secrets** (same values as every other MAAP repo):
   - `ecr_access_key`
   - `ecr_secret_key`
   - `staging_kubernetes_token`

### Deploying

```bash
scripts/deploy.sh --kanopy
```

Pushes the current HEAD of `main`. Drone takes over: Kaniko build →
Helm deploy. Watch at <https://drone.corp.mongodb.com>.

Seed a single pack once the backend pod is ready:

```bash
scripts/deploy.sh --kanopy finance
# or, manually (for every pack):
for d in reference healthcare finance retail telco; do
  kubectl exec -n maap deploy/mongodb-langchain-deep-agents-backend-web-app -- \
    env DOMAIN=$d MONGODB_DB=deep_agents_$d deep-agent --domain $d seed
done
```

### Rollback

```bash
helm -n maap rollback mongodb-langchain-deep-agents-backend
helm -n maap rollback mongodb-langchain-deep-agents-frontend
```

## Environment overrides

Every flag below is also honoured by `scripts/deploy.sh` so you can tune
a deploy without editing the script:

| Variable | Default | Purpose |
|---|---|---|
| `DEEP_AGENT_PORT` | `8010` | Host port for the backend (container is always 8000). |
| `FRONTEND_PORT` | `3000` | Host port for the frontend nginx. |
| `TIMEOUT` | `180` | Seconds to wait for `GET /health` before failing. |
| `MONGODB_DB_PREFIX` | `deep_agents` | Database prefix; per-pack DB is `<prefix>_<pack>`. |
| `COMPOSE` | `docker compose` | Override the compose CLI (e.g. `podman compose`). |
| `NO_BUILD` | `0` | Skip image rebuild on deploy. |
| `NO_SEED` | `0` | Skip the seed step. |
| `NO_FRONTEND` | `0` | Skip the frontend container. |

## Utility commands

```bash
scripts/deploy.sh --status     # show running Docker services + Kanopy pods
scripts/deploy.sh --down       # tear down the compose stack
scripts/deploy.sh --help       # full usage
```

## Troubleshooting

### Preflight fails with "MONGODB_URI ... still has a placeholder value"

`.env` contains `USER:PASS` or `...` in the URI. Fill in the actual
Atlas connection string.

### "service did not become healthy within 180s"

Usually means the backend container can't reach Atlas. Check:

```bash
docker compose logs deep_agent | tail -60
```

Look for `connection refused`, DNS errors, or `Failed to connect to MongoDB`.
Most common causes:

- Atlas IP allowlist doesn't include your machine's egress IP
- `MONGODB_URI` missing `?retryWrites=true&w=majority`
- Atlas user doesn't have cluster-wide read/write

### "tool_use ids were found without tool_result blocks"

Should not happen on Opus 4.7 with this codebase — if it does, check
that `LLM_MODEL=global.anthropic.claude-opus-4-7` exactly (no date
suffix) and that `src/deep_agent/middleware/patch_dangling.py` is being
loaded. `docker compose logs deep_agent | grep patch_dangling` will
confirm the middleware is running.

### Plan drawer stays empty

The planner only calls `write_todos` for multi-step prompts. For single
lookups ("list all X") it skips planning. Try a multi-step prompt like
the ones in the UI's starter-prompt chips.

### VFS writes land in the wrong database

Verify the per-domain thread scoping: every `/chat` call carries an
`X-Domain` header (the frontend sends it automatically). Without it the
backend falls back to `MONGODB_DB` without a suffix. Check by:

```bash
curl -sS http://localhost:8010/health
# → "db":"deep_agents_<default-domain>"
```

### Kanopy deploy step: "no Helm release found"

First-time deploys can take ~5 min for the chart to fetch and the pods
to become ready. Check pod status:

```bash
kubectl -n maap get pods -l app.kubernetes.io/instance=mongodb-langchain-deep-agents-backend
```

## Related documents

- [architecture.md](./architecture.md) — system-level design
- [configuration.md](./configuration.md) — every env var the backend reads
- [deployment.md](./deployment.md) — lower-level Atlas + Docker mechanics
- [vfs-backends.md](./vfs-backends.md) — GridFS vs S3 VFS
- [security.md](./security.md) — TLS, RBAC, secret handling
