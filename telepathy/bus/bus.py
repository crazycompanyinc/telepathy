"""Synchronous publish/subscribe event bus."""

from __future__ import annotations

import threading
from collections.abc import Callable

from telepathy.core.models import WorkspaceEvent, WorkspaceSnapshot
from telepathy.room.room import WorkspaceRoom
from telepathy.subscriptions.subscriptions import SubscriptionManager

Subscriber = Callable[[WorkspaceEvent, WorkspaceSnapshot], None]


class EventBus:
    """Publishes events, mutates the room, and notifies subscribers."""

    def __init__(self, room: WorkspaceRoom, subscriptions: SubscriptionManager | None = None):
        self.room = room
        self.subscriptions = subscriptions
        self._lock = threading.RLock()
        self._subscribers: dict[str, Subscriber] = {}

    def subscribe(self, name: str, callback: Subscriber) -> None:
        with self._lock:
            self._subscribers[name] = callback

    def unsubscribe(self, name: str) -> None:
        with self._lock:
            self._subscribers.pop(name, None)

    def publish(self, event: WorkspaceEvent) -> WorkspaceSnapshot:
        snapshot = self.room.apply_event(event)
        with self._lock:
            subscribers = list(self._subscribers.items())
        for _, callback in subscribers:
            callback(event, snapshot)
        return snapshot
