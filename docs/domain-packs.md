# Domain Packs

Swap the vertical by setting one environment variable. Five packs ship
out of the box: `reference`, `healthcare`, `finance`, `telco`, `retail`.

```bash
# Deploy the retail pack end-to-end
scripts/deploy.sh retail

# Or deploy every pack into per-domain DBs
scripts/deploy.sh --all

# Or swap packs without the deploy wrapper
DOMAIN=finance uv run deep-agent seed
DOMAIN=finance uv run deep-agent serve
```

## Pack layout

Each pack is a directory at the repo root:

```
domains/
|-- reference/
|-- healthcare/
|-- finance/
|-- telco/
\-- retail/
```

Inside a pack:

```
domains/<name>/
|-- pack.yaml          # manifest (name, description, allow_list)
|-- prompts.py         # MAIN_PROMPT + RESEARCHER_PROMPT
|-- README.md          # operator-facing pack description
\-- seeds/
    |-- knowledge_base.json
    |-- knowledge_graph.json
    \-- operational/
        \-- <collection>.json
```

## Manifest schema (`pack.yaml`)

| Key | Type | Description |
|---|---|---|
| `name` | string | Must match the directory name. |
| `description` | string | One-paragraph summary shown in docs and logs. |
| `allow_list` | list of strings | Collection names the data agent may query. Must equal the set of `operational/*.json` file stems. |

## Prompt contract (`prompts.py`)

Two module-level string constants, both required:

| Constant | Role |
|---|---|
| `MAIN_PROMPT` | System prompt for the planning agent. Must instruct the agent to call `write_todos`, delegate via `task`, and synthesize a final answer. |
| `RESEARCHER_PROMPT` | System prompt for the researcher subagent. Must name the KB tools (`knowledge_base_search`, `knowledge_base_hybrid_search`, `knowledge_graph_search`) and the web tools (`web_search`, `fetch_and_cache`). |

Anything else (additional constants, helpers) is ignored by the loader.

## Seed formats

| File | Format | Written to |
|---|---|---|
| `knowledge_base.json` | JSON array of `{"text": "...", "metadata": {...}}` | `knowledge_base` via `MongoDBAtlasVectorSearch.add_texts` |
| `knowledge_graph.json` | JSON array of `{"text": "...", "metadata": {...}}` | `MongoDBGraphStore.add_documents` (LLM extracts triples) |
| `operational/<stem>.json` | JSON array of documents | collection `<stem>` via `insert_many` |

The allow-list in `pack.yaml` MUST equal the set of operational stems.

## Selection precedence

The active pack is resolved at `get_active_pack()` first call and cached
for the process lifetime. In precedence order:

1. CLI flag: `deep-agent --domain <name> <subcommand>` sets the env var
   before settings load.
2. Environment: `DOMAIN=<name>`.
3. Default: `reference`.

`DOMAINS_ROOT` overrides the packs directory (default: `<repo>/domains`).

Path traversal (`DOMAIN=../evil`, `DOMAIN=foo/bar`) is rejected by the
`Settings` validator with `ValueError`.

## Single-command deploy: `scripts/deploy.sh`

```bash
scripts/deploy.sh <domain>           # Docker, single pack in deep_agents_<pack>
scripts/deploy.sh --all              # Docker, every pack, one backend
scripts/deploy.sh --kanopy           # Drone pipeline (staging)
scripts/deploy.sh --status           # show running containers / pods
scripts/deploy.sh --down             # tear down the Docker stack
```

Single-pack flow:

1. Preflight (`.env` present with valid keys, `docker compose` available, `curl` installed).
2. Build images (skippable with `NO_BUILD=1`).
3. Export `DOMAIN=<domain>` and `MONGODB_DB=deep_agents_<domain>`.
4. `docker compose up -d` (backend + frontend; `NO_FRONTEND=1` skips the UI).
5. Wait on `GET /health` until 200 (`TIMEOUT=180` seconds by default).
6. `deep-agent --domain <domain> seed` inside the container.
7. Print the URL set and a one-liner `curl` test.

`--all` differs in step 3 only: it uses `MONGODB_DB=<prefix>` and loops every
pack under `domains/` for seeding, so each lands in its own
`<prefix>_<pack>` database.

Idempotent: rerunning is safe. Seeds bulk-insert; running twice produces
duplicate rows unless you drop the DB between runs. Failures before
completion auto-tear-down the compose stack so a re-run starts clean.

See [DEPLOY.md](./DEPLOY.md) for the complete deployment reference
(Docker, Kanopy, environment overrides, troubleshooting).

## Quality gates

`tests/unit/test_quality_gates.py` enforces pack structure:

- `test_TC_20_040_five_packs_shipped` - exactly the five shipped packs exist.
- `test_TC_20_041_pack_has_required_files` - each pack has
  `pack.yaml`, `prompts.py`, `README.md`, and the three seed files.
- `test_TC_20_042_pack_allow_list_matches_seeds` - manifest's
  `allow_list` equals the set of operational stems.
- `test_TC_20_043_pack_prompts_reference_domain_vocab` - each non-reference
  pack's prompts mention domain-specific nouns (patient, account, subscriber,
  order).
- `test_TC_15_050_domain_isolated` - core code has no industry-term leakage.
- `test_TC_15_051_core_does_not_read_domain_seeds_directly` - only
  ingestion reads pack seeds.

## Per-domain integration tests

`tests/integration/test_per_domain.py` is parametrized over all five packs
and gated on `ATLAS_URI` + `VOYAGE_API_KEY`. For each pack it allocates a
fresh test DB, seeds the pack, runs one `knowledge_base_search` for a
pack-specific anchor phrase, and asserts a hit:

| Pack | Query | Token fuzzy-match |
|---|---|---|
| reference | "Atlas Vector Search" | `vector search`, `$vectorsearch` |
| healthcare | "vancomycin treatment" | `vancomycin`, `fidaxomicin`, `cdi` |
| finance | "Regulation E dispute window" | `regulation e`, `dispute`, `1005` |
| telco | "MTTR target SLA breach" | `mttr`, `sla`, `tier` |
| retail | "return policy 30 days" | `return`, `30 days`, `delivery` |

Run: `ATLAS_URI=... VOYAGE_API_KEY=... uv run pytest -m integration -v -k per_domain`

## Authoring a new pack

1. Create `domains/<yourname>/` with the four files + seeds.
2. Rewrite `prompts.py` in your domain voice; keep the two required symbols.
3. Populate `seeds/knowledge_base.json` with 6-15 policy documents.
4. Populate `seeds/knowledge_graph.json` with 3-8 entity-relation paragraphs.
5. Add operational collections (at least one) with 5+ realistic rows each.
6. Update `pack.yaml:allow_list` to match the operational stems.
7. Write `README.md` with personas, schema, hard rules.
8. Add an anchor phrase to `_PACK_ANCHORS` in
   `tests/integration/test_per_domain.py`.
9. Add the pack to `SHIPPED_PACKS` in `tests/unit/test_quality_gates.py`
   if you want it validated by quality gates (or keep it local-only).
10. `uv run pytest` + `uv run ruff check` + `uv run mypy --strict src`.

## Security note

The data-agent allow-list is per-pack. When deploying a pack against a
least-privilege Atlas role (`deep_agent_dataagent`), update the role's
collection grants to match the active pack's `allow_list`. See
[security.md](security.md).
