"""Sub-phase 15: LangSmith evals runner."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clear_settings() -> None:
    from deep_agent import config

    config.get_settings.cache_clear()


def test_TC_15_010_evals_runs_client_evaluate() -> None:
    fake_client = MagicMock()
    fake_client.evaluate.return_value = MagicMock()
    fake_graph = MagicMock()

    with patch("deep_agent.evals.Client", return_value=fake_client), patch(
        "deep_agent.evals.build_graph", return_value=fake_graph
    ):
        from deep_agent.evals import run_evaluation

        run_evaluation(dataset_name="my-dataset")

    fake_client.evaluate.assert_called_once()
    _, kwargs = fake_client.evaluate.call_args
    assert kwargs["data"] == "my-dataset"


def test_TC_15_011_target_extracts_last_ai_message() -> None:
    from langchain_core.messages import AIMessage

    fake_graph = MagicMock()
    fake_graph.invoke.return_value = {"messages": [AIMessage(content="answer-text")]}

    with patch("deep_agent.evals.build_graph", return_value=fake_graph):
        from deep_agent.evals import _default_target

        target = _default_target()
        out = target({"message": "what?"})

    assert out == {"answer": "answer-text"}


def test_TC_15_012_target_accepts_question_alias() -> None:
    from langchain_core.messages import AIMessage

    fake_graph = MagicMock()
    fake_graph.invoke.return_value = {"messages": [AIMessage(content="ok")]}
    with patch("deep_agent.evals.build_graph", return_value=fake_graph):
        from deep_agent.evals import _default_target

        assert _default_target()({"question": "q?"}) == {"answer": "ok"}


def test_TC_15_013_correctness_substring_match() -> None:
    from deep_agent.evals import _correctness_evaluator

    hit = MagicMock(outputs={"answer": "The capital is Paris."})
    expected_hit = MagicMock(outputs={"answer": "Paris"})
    assert _correctness_evaluator(hit, expected_hit).score == 1.0

    miss = MagicMock(outputs={"answer": "London"})
    expected_miss = MagicMock(outputs={"answer": "Paris"})
    assert _correctness_evaluator(miss, expected_miss).score == 0.0

    empty = MagicMock(outputs=None)
    assert _correctness_evaluator(empty, empty).score == 0.0


def test_TC_15_014_main_wires_argparse() -> None:
    with patch("deep_agent.evals.run_evaluation") as re:
        from deep_agent.evals import main

        rc = main(["--dataset", "my-ds", "--prefix", "exp"])

    assert rc == 0
    _, kwargs = re.call_args
    assert kwargs["dataset_name"] == "my-ds"
    assert kwargs["experiment_prefix"] == "exp"
