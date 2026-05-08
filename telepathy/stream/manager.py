"""WebSocket connection manager."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from fastapi import WebSocket

from telepathy.core.models import WorkspaceEvent
from telepathy.radar.engine import RadarEngine
from telepathy.subscriptions.subscriptions import SubscriptionManager


@dataclass
class StreamConnection:
    connection_id: str
    agent_id: str
    websocket: WebSocket
    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)


class StreamManager:
    """Tracks connected agents and pushes relevant events."""

    def __init__(self, radar: RadarEngine, subscriptions: SubscriptionManager):
        self.radar = radar
        self.subscriptions = subscriptions
        self._connections: dict[str, StreamConnection] = {}
        self._lock = asyncio.Lock()

    async def connect(self, agent_id: str, websocket: WebSocket) -> StreamConnection:
        await websocket.accept()
        connection = StreamConnection(str(uuid4()), agent_id, websocket)
        async with self._lock:
            self._connections[connection.connection_id] = connection
        await websocket.send_json({"type": "snapshot", "data": self.radar.get_agent_view(agent_id)})
        return connection

    async def disconnect(self, connection_id: str) -> None:
        async with self._lock:
            self._connections.pop(connection_id, None)

    async def push_event(self, event: WorkspaceEvent) -> None:
        async with self._lock:
            connections = list(self._connections.values())
        payload = {"type": "event", "event": event.model_dump(mode="json")}
        for connection in connections:
            if self.subscriptions.cares_about(connection.agent_id, event):
                await connection.queue.put(payload)

    async def broadcast_snapshot(self) -> None:
        async with self._lock:
            connections = list(self._connections.values())
        for connection in connections:
            await connection.queue.put({"type": "snapshot", "data": self.radar.get_agent_view(connection.agent_id)})

    async def sender_loop(self, connection: StreamConnection) -> None:
        while True:
            payload = await connection.queue.get()
            await connection.websocket.send_json(payload)

    async def heartbeat_loop(self, connection: StreamConnection, interval: float = 30.0) -> None:
        while True:
            await asyncio.sleep(interval)
            await connection.websocket.send_json({"type": "heartbeat", "agent_id": connection.agent_id})

    async def active_connection_count(self) -> int:
        async with self._lock:
            return len(self._connections)
