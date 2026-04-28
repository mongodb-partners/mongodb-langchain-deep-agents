"""Sub-phase 04: persistence surface factories."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    from deep_agent import config, models
    from deep_agent.persistence import mongo

    config.get_settings.cache_clear()
    models.get_llm.cache_clear()
    models.get_embeddings.cache_clear()
    models.get_reranker.cache_clear()
    mongo.reset_for_tests()


def test_TC_04_010_build_checkpointer() -> None:
    from deep_agent.persistence import checkpointer

    fake_client = MagicMock()
    with patch("deep_agent.persistence.checkpointer.MongoDBSaver") as saver, patch(
        "deep_agent.persistence.checkpointer.get_client", return_value=fake_client
    ):
        checkpointer.build_checkpointer()
    _, kwargs = saver.call_args
    assert kwargs["client"] is fake_client
    assert kwargs["db_name"] == "deep_agent_test"
    assert kwargs["checkpoint_collection_name"] == "checkpoints"
    assert kwargs["writes_collection_name"] == "checkpoint_writes"


def test_TC_04_020_build_store() -> None:
    from deep_agent.persistence import store

    fake_embedder = MagicMock()
    fake_db = MagicMock()
    with patch("deep_agent.persistence.store.MongoDBStore") as s_cls, patch(
        "deep_agent.persistence.store.get_db", return_value=fake_db
    ), patch("deep_agent.persistence.store.get_embeddings", return_value=fake_embedder), patch(
        "deep_agent.persistence.store.create_vector_index_config"
    ) as mk_cfg:
        mk_cfg.return_value = {"cfg": True}
        store.build_store()
    _, kwargs = s_cls.call_args
    # collection was the configured long-term memory collection
    fake_db.__getitem__.assert_called_once_with("long_term_memory")
    assert kwargs["index_config"] == {"cfg": True}
    assert kwargs["auto_index_timeout"] == 0
    # index config received dims + embedder + configured index name
    _, cfg_kwargs = mk_cfg.call_args
    assert cfg_kwargs["dims"] == 1024
    assert cfg_kwargs["embed"] is fake_embedder
    assert cfg_kwargs["name"] == "memory_semantic_index"


def test_TC_04_021_build_namespace() -> None:
    from deep_agent.persistence.store import build_namespace

    assert build_namespace("alice") == ("user", "alice", "memories")


def test_TC_04_030_build_chat_history() -> None:
    from deep_agent.persistence import chat_history

    with patch("deep_agent.persistence.chat_history.MongoDBChatMessageHistory") as cls:
        chat_history.build_chat_history("session-xyz")
    _, kwargs = cls.call_args
    assert kwargs["session_id"] == "session-xyz"
    assert kwargs["database_name"] == "deep_agent_test"
    assert kwargs["collection_name"] == "chat_history"
    assert kwargs["create_index"] is True


def test_TC_04_040_install_semantic_cache() -> None:
    from deep_agent.persistence import semantic_cache

    with patch("deep_agent.persistence.semantic_cache.MongoDBAtlasSemanticCache") as cls, patch(
        "deep_agent.persistence.semantic_cache.set_llm_cache"
    ) as set_cache, patch(
        "deep_agent.persistence.semantic_cache.get_embeddings", return_value=MagicMock()
    ):
        cls.return_value = MagicMock()
        cache = semantic_cache.install_semantic_cache()

    assert semantic_cache.is_installed() is True
    _, kwargs = cls.call_args
    assert kwargs["collection_name"] == "llm_cache"
    assert kwargs["database_name"] == "deep_agent_test"
    assert kwargs["index_name"] == "llm_cache_semantic_index"
    assert kwargs["score_threshold"] == 0.9
    set_cache.assert_called_once_with(cache)


def test_TC_04_041_install_semantic_cache_idempotent_flag() -> None:
    from deep_agent.persistence import semantic_cache

    with patch("deep_agent.persistence.semantic_cache.MongoDBAtlasSemanticCache"), patch(
        "deep_agent.persistence.semantic_cache.set_llm_cache"
    ), patch("deep_agent.persistence.semantic_cache.get_embeddings", return_value=MagicMock()):
        semantic_cache.install_semantic_cache()
        semantic_cache.install_semantic_cache()
    assert semantic_cache.is_installed() is True


def test_TC_04_050_build_vector_store() -> None:
    from deep_agent.persistence import vector_store

    fake_db = MagicMock()
    fake_embedder = MagicMock()
    with patch("deep_agent.persistence.vector_store.MongoDBAtlasVectorSearch") as cls, patch(
        "deep_agent.persistence.vector_store.get_db", return_value=fake_db
    ), patch("deep_agent.persistence.vector_store.get_embeddings", return_value=fake_embedder):
        vector_store.build_vector_store()
    _, kwargs = cls.call_args
    fake_db.__getitem__.assert_called_once_with("knowledge_base")
    assert kwargs["index_name"] == "vector_index"
    assert kwargs["text_key"] == "text"
    assert kwargs["embedding_key"] == "embedding"
    assert kwargs["relevance_score_fn"] == "cosine"
    assert kwargs["dimensions"] == 1024
    assert kwargs["auto_create_index"] is False
    assert kwargs["embedding"] is fake_embedder


def test_TC_04_060_build_graph_store() -> None:
    from deep_agent.persistence import graph_store

    fake_db = MagicMock()
    fake_llm = MagicMock()
    with patch("deep_agent.persistence.graph_store.MongoDBGraphStore") as cls, patch(
        "deep_agent.persistence.graph_store.get_db", return_value=fake_db
    ), patch("deep_agent.persistence.graph_store.get_llm", return_value=fake_llm):
        graph_store.build_graph_store()
    _, kwargs = cls.call_args
    fake_db.__getitem__.assert_called_once_with("knowledge_graph")
    assert kwargs["entity_extraction_model"] is fake_llm


# -------------------- Spec 400: db_name plumbing --------------------


def test_TC_40_411_build_checkpointer_db_name() -> None:
    """REQ-E-411: build_checkpointer(db_name=...) binds the saver to that DB."""
    from deep_agent.persistence import checkpointer

    fake_client = MagicMock()
    with patch("deep_agent.persistence.checkpointer.MongoDBSaver") as saver, patch(
        "deep_agent.persistence.checkpointer.get_client", return_value=fake_client
    ):
        checkpointer.build_checkpointer(db_name="deep_agent_override")
    _, kwargs = saver.call_args
    assert kwargs["db_name"] == "deep_agent_override"


def test_TC_40_INV_403_build_checkpointer_no_arg() -> None:
    """INV-403: no-arg build_checkpointer still uses Settings.mongodb_db."""
    from deep_agent.persistence import checkpointer

    with patch("deep_agent.persistence.checkpointer.MongoDBSaver") as saver, patch(
        "deep_agent.persistence.checkpointer.get_client", return_value=MagicMock()
    ):
        checkpointer.build_checkpointer()
    _, kwargs = saver.call_args
    assert kwargs["db_name"] == "deep_agent_test"


def test_TC_40_411_build_store_db_name() -> None:
    """REQ-E-411: build_store(db_name=...) routes the underlying get_db call."""
    from deep_agent.persistence import store

    fake_db = MagicMock()
    # get_db must be called with the explicit name; record the call.
    with patch("deep_agent.persistence.store.MongoDBStore"), patch(
        "deep_agent.persistence.store.get_db", return_value=fake_db
    ) as get_db_m, patch(
        "deep_agent.persistence.store.get_embeddings", return_value=MagicMock()
    ), patch("deep_agent.persistence.store.create_vector_index_config"):
        store.build_store(db_name="deep_agent_override")
    get_db_m.assert_called_once_with("deep_agent_override")


def test_TC_40_INV_403_build_store_no_arg() -> None:
    """INV-403: no-arg build_store still calls get_db() without a db_name."""
    from deep_agent.persistence import store

    fake_db = MagicMock()
    with patch("deep_agent.persistence.store.MongoDBStore"), patch(
        "deep_agent.persistence.store.get_db", return_value=fake_db
    ) as get_db_m, patch(
        "deep_agent.persistence.store.get_embeddings", return_value=MagicMock()
    ), patch("deep_agent.persistence.store.create_vector_index_config"):
        store.build_store()
    # no arg → get_db(None) or get_db() both route to Settings.mongodb_db
    args, kwargs = get_db_m.call_args
    assert args in ((), (None,))
    assert not kwargs


def test_TC_40_411_build_chat_history_db_name() -> None:
    """REQ-E-411: build_chat_history accepts db_name override."""
    from deep_agent.persistence import chat_history

    with patch("deep_agent.persistence.chat_history.MongoDBChatMessageHistory") as cls:
        chat_history.build_chat_history("sess", db_name="deep_agent_override")
    _, kwargs = cls.call_args
    assert kwargs["database_name"] == "deep_agent_override"


def test_TC_40_INV_403_build_chat_history_no_arg() -> None:
    """INV-403: no-arg build_chat_history still uses Settings.mongodb_db."""
    from deep_agent.persistence import chat_history

    with patch("deep_agent.persistence.chat_history.MongoDBChatMessageHistory") as cls:
        chat_history.build_chat_history("sess")
    _, kwargs = cls.call_args
    assert kwargs["database_name"] == "deep_agent_test"


def test_TC_40_411_build_vector_store_db_name() -> None:
    """REQ-E-411: build_vector_store(db_name=...) routes to the named DB."""
    from deep_agent.persistence import vector_store

    fake_db = MagicMock()
    with patch("deep_agent.persistence.vector_store.MongoDBAtlasVectorSearch"), patch(
        "deep_agent.persistence.vector_store.get_db", return_value=fake_db
    ) as get_db_m, patch(
        "deep_agent.persistence.vector_store.get_embeddings", return_value=MagicMock()
    ):
        vector_store.build_vector_store(db_name="deep_agent_override")
    get_db_m.assert_called_once_with("deep_agent_override")


# -------------------- Spec 400: scoped_semantic_cache --------------------


def test_TC_40_420a_scoped_installs_and_sets_db_name() -> None:
    """REQ-E-420: scoped_semantic_cache(db_name) installs a cache bound to
    db_name as LangChain's global LLM cache for the duration of the block."""
    from deep_agent.persistence import semantic_cache as sc

    with patch("deep_agent.persistence.semantic_cache.MongoDBAtlasSemanticCache") as cls, patch(
        "deep_agent.persistence.semantic_cache.set_llm_cache"
    ) as set_cache, patch(
        "deep_agent.persistence.semantic_cache.get_llm_cache", return_value=None
    ), patch(
        "deep_agent.persistence.semantic_cache.get_embeddings", return_value=MagicMock()
    ):
        cls.return_value = MagicMock()
        with sc.scoped_semantic_cache("deep_agent_override") as cache:
            assert cache is cls.return_value
    # Cache was built for the given DB name.
    _, build_kwargs = cls.call_args
    assert build_kwargs["database_name"] == "deep_agent_override"
    # set_llm_cache was called twice: once to install, once to restore (prior None).
    assert set_cache.call_count == 2
    assert set_cache.call_args_list[0].args[0] is cls.return_value
    assert set_cache.call_args_list[1].args[0] is None


def test_TC_40_420b_scoped_restores_prior_cache_on_exit() -> None:
    """REQ-E-420: on exit, the prior global LLM cache is restored (not None
    when one was present before the scope)."""
    from deep_agent.persistence import semantic_cache as sc

    prior_sentinel = MagicMock(name="prior-cache")
    scoped_sentinel = MagicMock(name="scoped-cache")

    with patch(
        "deep_agent.persistence.semantic_cache.MongoDBAtlasSemanticCache",
        return_value=scoped_sentinel,
    ), patch(
        "deep_agent.persistence.semantic_cache.set_llm_cache"
    ) as set_cache, patch(
        "deep_agent.persistence.semantic_cache.get_llm_cache",
        return_value=prior_sentinel,
    ), patch(
        "deep_agent.persistence.semantic_cache.get_embeddings", return_value=MagicMock()
    ), sc.scoped_semantic_cache("deep_agent_override"):
        pass
    # Install then restore to prior.
    assert set_cache.call_args_list[0].args[0] is scoped_sentinel
    assert set_cache.call_args_list[1].args[0] is prior_sentinel


def test_TC_40_420_ascoped_install_and_restore() -> None:
    """REQ-E-420: async variant installs + restores across the async block."""
    import asyncio

    from deep_agent.persistence import semantic_cache as sc

    prior_sentinel = MagicMock(name="prior-cache")
    scoped_sentinel = MagicMock(name="scoped-cache")

    async def _exercise() -> None:
        with patch(
            "deep_agent.persistence.semantic_cache.MongoDBAtlasSemanticCache",
            return_value=scoped_sentinel,
        ), patch(
            "deep_agent.persistence.semantic_cache.set_llm_cache"
        ) as set_cache, patch(
            "deep_agent.persistence.semantic_cache.get_llm_cache",
            return_value=prior_sentinel,
        ), patch(
            "deep_agent.persistence.semantic_cache.get_embeddings",
            return_value=MagicMock(),
        ):
            async with sc.ascoped_semantic_cache("deep_agent_override"):
                pass
            assert set_cache.call_args_list[0].args[0] is scoped_sentinel
            assert set_cache.call_args_list[1].args[0] is prior_sentinel

    asyncio.run(_exercise())


def test_TC_40_INV_421_install_semantic_cache_unchanged() -> None:
    """INV-421: install_semantic_cache() still uses Settings.mongodb_db and
    sets the global cache. Unchanged from the single-domain CLI path."""
    from deep_agent.persistence import semantic_cache as sc

    with patch("deep_agent.persistence.semantic_cache.MongoDBAtlasSemanticCache") as cls, patch(
        "deep_agent.persistence.semantic_cache.set_llm_cache"
    ) as set_cache, patch(
        "deep_agent.persistence.semantic_cache.get_embeddings", return_value=MagicMock()
    ):
        cls.return_value = MagicMock()
        cache = sc.install_semantic_cache()
    _, kwargs = cls.call_args
    assert kwargs["database_name"] == "deep_agent_test"
    set_cache.assert_called_once_with(cache)


def test_TC_40_411_build_graph_store_db_name() -> None:
    """REQ-E-411: build_graph_store(db_name=...) routes to the named DB."""
    from deep_agent.persistence import graph_store

    fake_db = MagicMock()
    with patch("deep_agent.persistence.graph_store.MongoDBGraphStore"), patch(
        "deep_agent.persistence.graph_store.get_db", return_value=fake_db
    ) as get_db_m, patch(
        "deep_agent.persistence.graph_store.get_llm", return_value=MagicMock()
    ):
        graph_store.build_graph_store(db_name="deep_agent_override")
    get_db_m.assert_called_once_with("deep_agent_override")
