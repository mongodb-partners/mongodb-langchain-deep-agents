"""Custom deepagents middleware.

:class:`PlanPersistenceMiddleware` upserts the agent's todo list into MongoDB
on every ``after_model`` hook so operator dashboards see plan state without
replaying checkpoints.
"""
from .plan import PlanPersistenceMiddleware

__all__ = ["PlanPersistenceMiddleware"]
