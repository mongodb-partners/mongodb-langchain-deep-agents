# Evals

The repo ships a small LangSmith-compatible starter dataset plus an uploader
script. After uploading, `deep-agent-evals --dataset deep_agent_starter`
runs the compiled graph against every example and scores a substring-match
correctness evaluator.

## What ships

| Path | Purpose |
|---|---|
| `tests/fixtures/evals_dataset.jsonl` | 8 `{message, answer}` rows exercising the KB, VFS, plan, and safety-wrapper stories |
| `scripts/create_evals_dataset.py` | Idempotent LangSmith uploader. Dedupes by `message`. |
| `src/deep_agent/evals.py` | `run_evaluation()` + `deep-agent-evals` CLI |

The starter rows are deliberately generic - their `answer` fields are
substrings that any correct explanation should include (e.g. `"vectorSearch"`,
`"checkpoints"`, `"fetch_and_cache"`), so the default evaluator does not
depend on prose-level phrasing.

## Prerequisites

- `LANGSMITH_API_KEY` set in the environment (or `.env`)
- A LangSmith workspace that the key can write to

## Upload

```bash
uv run python scripts/create_evals_dataset.py
```

Output:

```json
{
  "dataset_id": "...",
  "dataset_name": "deep_agent_starter",
  "already_present": 0,
  "created": 8
}
```

Re-running is safe. Already-uploaded rows (matched by `message`) are skipped;
new rows appended.

Custom name or fixture:

```bash
uv run python scripts/create_evals_dataset.py \
  --name my_project_smoke \
  --fixture path/to/my_dataset.jsonl \
  --description "Smoke set for my-project"
```

## Run an evaluation

```bash
uv run python -m deep_agent.evals --dataset deep_agent_starter
```

or via the installed console script:

```bash
uv run deep-agent-evals --dataset deep_agent_starter
```

Flags:

| Flag | Default |
|---|---|
| `--dataset NAME` | _(required)_ - LangSmith dataset name |
| `--prefix STR` | `deep_agent` - experiment name prefix |

`run_evaluation` builds the graph via `build_graph()`, so MongoDBSaver +
MongoDBStore + the semantic cache are all active during the run. This means
consecutive eval runs benefit from `llm_cache` hits - clear the cache
between runs if you need deterministic LLM invocation timing:

```bash
uv run python -c "
from deep_agent.persistence.mongo import get_db
from deep_agent.config import get_settings
s = get_settings()
get_db()[s.llm_cache_collection].delete_many({})
"
```

## The default evaluator

`_correctness_evaluator` in `src/deep_agent/evals.py`:

```python
def _correctness_evaluator(run, example) -> EvaluationResult:
    expected = (example.outputs or {}).get("answer", "") if example.outputs else ""
    actual = (run.outputs or {}).get("answer", "") if run.outputs else ""
    score = 1.0 if expected and expected.strip().lower() in actual.lower() else 0.0
    return EvaluationResult(key="correctness", score=score)
```

Substring, case-insensitive, 0.0 on any missing output. Adopters typically
replace this with a domain-specific evaluator (LLM-as-judge for rubric
scoring, structured output exact-match, etc.).

## Custom evaluator

Pass your own list to `Client.evaluate`:

```python
from langsmith import Client
from langsmith.evaluation import EvaluationResult

from deep_agent.evals import _default_target

def custom_eval(run, example) -> EvaluationResult:
    ...  # your scoring here
    return EvaluationResult(key="my_metric", score=...)

Client().evaluate(
    _default_target(),
    data="deep_agent_starter",
    evaluators=[custom_eval],
    experiment_prefix="deep_agent-custom",
)
```

`_default_target()` reads `message` (or `question` as an alias) from inputs,
invokes the graph, and returns `{"answer": <last AIMessage content>}`.

## Tests

`tests/unit/test_evals_dataset.py` covers:

- `TC-18-010`: fixture is valid JSONL with `message` + `answer` keys on every row
- `TC-18-020`: uploader creates a new dataset when one doesn't exist
- `TC-18-021`: re-running the uploader dedupes on `message`
- `TC-18-030`: `main()` parses `--name` / `--fixture` and prints the JSON summary

`tests/unit/test_evals.py` covers the eval runner itself:

- `TC-15-010..014`: `run_evaluation` wires to `Client.evaluate`; the target
  callable accepts both `message` and `question` input keys; the correctness
  evaluator handles substrings, misses, and missing outputs.

## Extending the starter dataset

Append JSONL rows to `tests/fixtures/evals_dataset.jsonl`:

```jsonl
{"message": "What does PlanPersistenceMiddleware do?", "answer": "after_model"}
{"message": "Which env var selects the VFS backend?", "answer": "VFS_BACKEND"}
```

Re-run the uploader; only new `message` values create examples.

Keep `answer` fields as substrings that must appear in a correct response.
Over-specific answers (exact prose) will score poorly; too-generic answers
(single common word) will false-positive.
