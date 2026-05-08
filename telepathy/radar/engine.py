"""Radar engine for workspace views."""

from __future__ import annotations

from typing import Any

from telepathy.core.models import WorkspaceSnapshot
from telepathy.room.room import WorkspaceRoom
from telepathy.subscriptions.subscriptions import SubscriptionManager


class RadarEngine:
    def __init__(self, room: WorkspaceRoom, subscriptions: SubscriptionManager | None = None):
        self.room = room
        self.subscriptions = subscriptions

    def get_snapshot(self) -> WorkspaceSnapshot:
        return self.room.get_snapshot()

    def get_agent_view(self, agent_id: str) -> dict[str, Any]:
        snapshot = self.get_snapshot().as_dict()
        if not self.subscriptions:
            return snapshot
        recent = [
            event
            for event in self.room.get_recent_events()
            if self.subscriptions.cares_about(agent_id, event)
        ]
        snapshot["recent_events"] = [event.model_dump(mode="json") for event in recent[-20:]]
        snapshot["viewer"] = agent_id
        return snapshot

    def get_file_status(self, path: str) -> dict[str, Any]:
        return self.room.get_file_status(path)

    def get_recent_events(self, event_type: str | None = None, target: str | None = None) -> list[dict[str, Any]]:
        return [event.model_dump(mode="json") for event in self.room.get_recent_events(event_type, target)]

    def get_predicted_conflicts(self) -> list[dict[str, Any]]:
        return self.get_snapshot().predicted_conflicts
