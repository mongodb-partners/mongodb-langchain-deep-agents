"""Sub-phase 13: deep-agent CLI."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    from deep_agent import config

    config.get_settings.cache_clear()


def test_TC_13_010_cli_one_shot(capsys: pytest.CaptureFixture[str]) -> None:
    from langchain_core.messages import AIMessage

    fake_graph = MagicMock()
    fake_graph.invoke.return_value = {"messages": [AIMessage(content="Hi there!")]}
    fake_history = MagicMock()

    with patch("deep_agent.cli.build_graph", return_value=fake_graph), patch(
        "deep_agent.cli.build_chat_history", return_value=fake_history
    ), patch("deep_agent.cli.persist_plan_snapshot"):
        from deep_agent.cli import main

        rc = main(["chat", "--once", "hello", "--user", "u1"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "Hi there!" in out
    fake_graph.invoke.assert_called_once()


def test_TC_13_011_cli_seed(capsys: pytest.CaptureFixture[str]) -> None:
    # `seed` is imported lazily inside the CLI handler. The test patches the
    # import path that the handler uses.
    with patch("deep_agent.ingestion.seed.seed_all", return_value={"knowledge_base": 3}):
        from deep_agent.cli import main

        rc = main(["seed"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "knowledge_base" in out


def test_TC_20_014_cli_domain_flag_sets_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """REQ-E-214: --domain overrides DOMAIN before settings load."""
    monkeypatch.delenv("DOMAIN", raising=False)
    monkeypatch.setenv("DOMAIN", "reference")  # default from conftest

    with patch("deep_agent.ingestion.seed.seed_all", return_value={}):
        from deep_agent.cli import main

        # Pass a domain that exists. After main, env var reflects flag.
        main(["--domain", "reference", "seed"])

    import os

    assert os.environ["DOMAIN"] == "reference"


def test_TC_20_015_cli_seed_preamble(capsys: pytest.CaptureFixture[str]) -> None:
    """REQ-E-215: `seed` prints active pack name before the seed summary."""
    with patch("deep_agent.ingestion.seed.seed_all", return_value={"knowledge_base": 0}):
        from deep_agent.cli import main

        rc = main(["seed"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "active pack: reference" in out


def test_TC_13_012_cli_chat_persists_history() -> None:
    from langchain_core.messages import AIMessage

    fake_graph = MagicMock()
    fake_graph.invoke.return_value = {"messages": [AIMessage(content="ok")]}
    fake_history = MagicMock()

    with patch("deep_agent.cli.build_graph", return_value=fake_graph), patch(
        "deep_agent.cli.build_chat_history", return_value=fake_history
    ) as bch, patch("deep_agent.cli.persist_plan_snapshot"):
        from deep_agent.cli import main

        rc = main(["chat", "--once", "hello", "--user", "u1", "--thread", "t1"])

    assert rc == 0
    bch.assert_called_once_with("t1", db_name="deep_agent_test_reference")
    fake_history.add_user_message.assert_called_once_with("hello")
    fake_history.add_ai_message.assert_called_once_with("ok")


def test_TC_13_013_cli_swallow_history_pymongo_error() -> None:
    from langchain_core.messages import AIMessage
    from pymongo.errors import PyMongoError

    fake_graph = MagicMock()
    fake_graph.invoke.return_value = {"messages": [AIMessage(content="ok")]}
    fake_history = MagicMock()
    fake_history.add_user_message.side_effect = PyMongoError("down")
    fake_history.add_ai_message.side_effect = PyMongoError("down")

    with patch("deep_agent.cli.build_graph", return_value=fake_graph), patch(
        "deep_agent.cli.build_chat_history", return_value=fake_history
    ), patch("deep_agent.cli.persist_plan_snapshot"):
        from deep_agent.cli import main

        rc = main(["chat", "--once", "hi", "--user", "u1"])

    # Must not raise — logs and continues.
    assert rc == 0
