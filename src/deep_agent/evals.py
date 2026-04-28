"""LangSmith-powered evaluation runner.

Usage:

    deep-agent-evals --dataset my-dataset

The graph is wrapped in a thin callable that accepts ``{"message": str}``
inputs and returns ``{"answer": str}`` — matching the dataset schema used
in LangSmith examples. Evaluators default to a simple ``correctness``
placeholder that adopters override for their domain.
"""
from __future__ import annotations

import argparse
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langsmith import Client
from langsmith.evaluation import EvaluationResult

from .graph import build_graph


def _default_target() -> Any:
    """Return a dataset-compatible target callable: ``{"message": str} -> {"answer": str}``."""
    graph = build_graph()

    def target(inputs: dict[str, Any]) -> dict[str, Any]:
        message = inputs.get("message") or inputs.get("question") or ""
        state = graph.invoke(
            {
                "messages": [HumanMessage(content=str(message))],
                "user_id": "evals",
            },
            config={"configurable": {"thread_id": "evals", "user_id": "evals"}},
        )
        msgs = state.get("messages", []) if isinstance(state, dict) else []
        answer = ""
        for m in reversed(msgs):
            if isinstance(m, AIMessage):
                answer = str(m.content)
                break
        return {"answer": answer}

    return target


def _correctness_evaluator(run: Any, example: Any) -> EvaluationResult:
    """Placeholder correctness check — matches ``answer`` substring. Override for real evals."""
    expected = (example.outputs or {}).get("answer", "") if example.outputs else ""
    actual = (run.outputs or {}).get("answer", "") if run.outputs else ""
    score = 1.0 if expected and expected.strip().lower() in actual.lower() else 0.0
    return EvaluationResult(key="correctness", score=score)


def run_evaluation(*, dataset_name: str, experiment_prefix: str = "deep_agent") -> Any:
    """Run the graph against a LangSmith dataset and return the experiment results."""
    client = Client()
    return client.evaluate(
        _default_target(),
        data=dataset_name,
        evaluators=[_correctness_evaluator],
        experiment_prefix=experiment_prefix,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="deep-agent-evals")
    p.add_argument("--dataset", required=True, help="LangSmith dataset name or ID")
    p.add_argument("--prefix", default="deep_agent", help="Experiment name prefix")
    args = p.parse_args(argv)
    run_evaluation(dataset_name=args.dataset, experiment_prefix=args.prefix)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
