# Domain Adaptation

Retarget any vertical by selecting a domain pack. See
[domain-packs.md](domain-packs.md) for the full authoring guide - this
page is a five-minute summary.

## Swap a pack

```bash
DOMAIN=healthcare uv run deep-agent seed
DOMAIN=healthcare uv run deep-agent serve
```

Or the one-shot:

```bash
scripts/deploy.sh healthcare
```

## Pack structure

```
domains/<name>/
|-- pack.yaml          # name, description, allow_list
|-- prompts.py         # MAIN_PROMPT + RESEARCHER_PROMPT
|-- README.md          # operator doc
\-- seeds/
    |-- knowledge_base.json
    |-- knowledge_graph.json
    \-- operational/<collection>.json
```

## What must not leak into core

Core modules (anything under `src/deep_agent/` except the `domain_pack`
loader) must not:

- import pack content directly (use `get_active_pack()`)
- reference industry-specific vocabulary in identifiers or strings
- hard-code collection names tied to a specific industry schema

Quality gates (`tests/unit/test_quality_gates.py`):

- `test_TC_15_050_domain_isolated` - greps core `.py` for forbidden terms
- `test_TC_15_051_core_does_not_read_domain_seeds_directly`
- `test_TC_20_040..044` - pack structure + manifest integrity

## Five-step authoring recipe

1. `cp -r domains/reference domains/yourname`
2. Rewrite `pack.yaml` (name, description, allow_list).
3. Rewrite `prompts.py` in your domain voice - keep both symbols.
4. Replace seeds: KB, graph, operational collections. Allow-list must
   equal the set of operational stems.
5. `DOMAIN=yourname uv run deep-agent seed` + `uv run pytest`.

Full details in [domain-packs.md](domain-packs.md).

## Advanced

Adding subagents, new tools, or new MongoDB surfaces stays in
`src/deep_agent/` - not in packs. See
[developer-guide.md](developer-guide.md).
