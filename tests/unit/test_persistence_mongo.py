"""Sub-phase 03: mongo.py singleton client."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    from deep_agent import config
    from deep_agent.persistence import mongo

    config.get_settings.cache_clear()
    mongo.reset_for_tests()


def test_TC_03_010_get_client_is_singleton() -> None:
    from deep_agent.persistence import mongo

    with patch("deep_agent.persistence.mongo.MongoClient") as mc:
        mc.return_value = MagicMock()
        a = mongo.get_client()
        b = mongo.get_client()
    assert a is b
    mc.assert_called_once()
    args, _ = mc.call_args
    assert args[0].startswith("mongodb://")


def test_TC_03_015_get_client_redacts_uri_on_failure() -> None:
    from pymongo.errors import PyMongoError

    from deep_agent.persistence import mongo

    with patch("deep_agent.persistence.mongo.MongoClient") as mc:
        mc.side_effect = PyMongoError("kaboom")
        with pytest.raises(ConnectionError) as excinfo:
            mongo.get_client()

    message = str(excinfo.value)
    assert "[URI redacted]" in message
    assert "PyMongoError" in message
    assert "mongodb://" not in message
    assert "fake:27017" not in message


def test_TC_03_020_get_db_returns_configured_name() -> None:
    from deep_agent.persistence import mongo

    fake_client = MagicMock()
    with patch("deep_agent.persistence.mongo.get_client", return_value=fake_client):
        mongo.get_db()
    fake_client.__getitem__.assert_called_once_with("deep_agent_test")


def test_TC_03_025_reset_for_tests_clears_cache() -> None:
    from deep_agent.persistence import mongo

    with patch("deep_agent.persistence.mongo.MongoClient") as mc:
        mc.return_value = MagicMock()
        mongo.get_client()
        mongo.reset_for_tests()
        mongo.get_client()
    assert mc.call_count == 2


def test_TC_40_411_get_db_with_explicit_db_name() -> None:
    """REQ-E-411: get_db(db_name=...) binds to the named DB (web server path)."""
    from deep_agent.persistence import mongo

    fake_client = MagicMock()
    with patch("deep_agent.persistence.mongo.get_client", return_value=fake_client):
        mongo.get_db("deep_agent_overridden")
    fake_client.__getitem__.assert_called_once_with("deep_agent_overridden")


def test_TC_40_INV_403_get_db_no_arg_uses_settings() -> None:
    """INV-403: get_db() with no arg still binds to Settings.mongodb_db."""
    from deep_agent.persistence import mongo

    fake_client = MagicMock()
    with patch("deep_agent.persistence.mongo.get_client", return_value=fake_client):
        mongo.get_db()
        mongo.get_db(None)
    # Both no-arg and explicit-None resolve to the env-configured name.
    assert fake_client.__getitem__.call_args_list == [
        (("deep_agent_test",),),
        (("deep_agent_test",),),
    ]
