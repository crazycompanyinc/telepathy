"""Subscription filtering for real-time events."""

from __future__ import annotations

import threading

from telepathy.core.db import TelepathyDB
from telepathy.core.models import AgentSubscription, WorkspaceEvent
from telepathy.radar.conflict_prediction import targets_overlap


class SubscriptionManager:
    def __init__(self, db: TelepathyDB | None = None):
        self.db = db
        self._lock = threading.RLock()
        self._subscriptions: dict[str, list[AgentSubscription]] = {}
        if db:
            for sub in db.list_subscriptions():
                self._subscriptions.setdefault(sub.agent_id, []).append(sub)

    def subscribe(
        self,
        agent_id: str,
        event_types: list[str] | None = None,
        targets: list[str] | None = None,
    ) -> AgentSubscription:
        subscription = AgentSubscription(agent_id=agent_id, event_types=event_types or [], targets=targets or [])
        with self._lock:
            self._subscriptions.setdefault(agent_id, []).append(subscription)
        if self.db:
            self.db.save_subscription(subscription)
        return subscription

    def subscriptions_for(self, agent_id: str) -> list[AgentSubscription]:
        with self._lock:
            return list(self._subscriptions.get(agent_id, []))

    def cares_about(self, agent_id: str, event: WorkspaceEvent) -> bool:
        subscriptions = self.subscriptions_for(agent_id)
        if not subscriptions:
            return True
        for sub in subscriptions:
            type_match = not sub.event_types or event.event_type in sub.event_types
            target_match = not sub.targets or any(targets_overlap(event.target, target) for target in sub.targets)
            if type_match and target_match:
                return True
        return False
