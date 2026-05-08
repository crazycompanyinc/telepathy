"""FastAPI application factory."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from telepathy.bus.bus import EventBus
from telepathy.bus.events import make_event
from telepathy.core.db import TelepathyDB
from telepathy.core.models import EventType, WorkspaceEvent
from telepathy.radar.engine import RadarEngine
from telepathy.room.room import WorkspaceRoom
from telepathy.stream.manager import StreamManager
from telepathy.subscriptions.subscriptions import SubscriptionManager


class TelepathyRuntime:
    def __init__(self, db_path: str | Path = ".telepathy/telepathy.db"):
        self.db = TelepathyDB(db_path)
        self.room = WorkspaceRoom(self.db)
        self.subscriptions = SubscriptionManager(self.db)
        self.radar = RadarEngine(self.room, self.subscriptions)
        self.bus = EventBus(self.room, self.subscriptions)
        self.streams = StreamManager(self.radar, self.subscriptions)


def create_app(db_path: str | Path = ".telepathy/telepathy.db") -> FastAPI:
    runtime = TelepathyRuntime(db_path)
    app = FastAPI(title="Telepathy", version="0.1.0")
    app.state.telepathy = runtime

    async def publish(event_type: EventType | str, agent_id: str | None = None, target: str | None = None, data: dict[str, Any] | None = None):
        event = make_event(event_type, agent_id=agent_id, target=target, data=data)
        snapshot = runtime.bus.publish(event)
        await runtime.streams.push_event(event)
        await runtime.streams.broadcast_snapshot()
        return snapshot

    @app.post("/agents")
    def register_agent(payload: dict[str, Any]) -> dict[str, Any]:
        agent_id = payload["agent_id"]
        agent = runtime.room.register_agent(agent_id, payload.get("agent_name"), payload.get("agent_type", "agent"))
        return agent.model_dump(mode="json")

    @app.post("/agents/{agent_id}/join")
    async def join(agent_id: str) -> dict[str, Any]:
        return (await publish(EventType.AGENT_JOIN, agent_id=agent_id)).as_dict()

    @app.post("/agents/{agent_id}/leave")
    async def leave(agent_id: str) -> dict[str, Any]:
        return (await publish(EventType.AGENT_LEAVE, agent_id=agent_id)).as_dict()

    @app.post("/agents/{agent_id}/work")
    async def work(agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return (await publish(EventType.AGENT_WORKING, agent_id=agent_id, target=payload.get("target"), data=payload)).as_dict()

    @app.post("/agents/{agent_id}/idle")
    async def idle(agent_id: str) -> dict[str, Any]:
        return (await publish(EventType.AGENT_IDLE, agent_id=agent_id)).as_dict()

    @app.post("/files/lock")
    async def lock_file(payload: dict[str, Any]) -> dict[str, Any]:
        return (await publish(EventType.FILE_LOCK, agent_id=payload.get("agent_id"), target=payload["file"], data=payload)).as_dict()

    @app.post("/files/unlock")
    async def unlock_file(payload: dict[str, Any]) -> dict[str, Any]:
        return (await publish(EventType.FILE_UNLOCK, agent_id=payload.get("agent_id"), target=payload["file"], data=payload)).as_dict()

    @app.post("/events")
    async def event(payload: dict[str, Any]) -> dict[str, Any]:
        workspace_event = WorkspaceEvent.model_validate(payload)
        snapshot = runtime.bus.publish(workspace_event)
        await runtime.streams.push_event(workspace_event)
        await runtime.streams.broadcast_snapshot()
        return snapshot.as_dict()

    @app.get("/radar")
    def radar() -> dict[str, Any]:
        return runtime.radar.get_snapshot().as_dict()

    @app.get("/radar/agent/{agent_id}")
    def agent_radar(agent_id: str) -> dict[str, Any]:
        return runtime.radar.get_agent_view(agent_id)

    @app.get("/files/{path:path}/status")
    def file_status(path: str) -> dict[str, Any]:
        return runtime.radar.get_file_status(path)

    @app.get("/conflicts")
    def conflicts() -> list[dict[str, Any]]:
        return runtime.radar.get_predicted_conflicts()

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "connections": await runtime.streams.active_connection_count()}

    @app.websocket("/ws/agent/{agent_id}")
    async def websocket_agent(websocket: WebSocket, agent_id: str) -> None:
        connection = await runtime.streams.connect(agent_id, websocket)
        sender = asyncio.create_task(runtime.streams.sender_loop(connection))
        heartbeat = asyncio.create_task(runtime.streams.heartbeat_loop(connection))
        try:
            while True:
                message = await websocket.receive_json()
                if message.get("type") == "heartbeat":
                    runtime.room.heartbeat(agent_id)
                elif message.get("type") == "subscribe":
                    runtime.subscriptions.subscribe(
                        agent_id,
                        message.get("event_types") or [],
                        message.get("targets") or [],
                    )
                elif message.get("type") == "event":
                    event = WorkspaceEvent.model_validate(message["event"])
                    runtime.bus.publish(event)
                    await runtime.streams.push_event(event)
                    await runtime.streams.broadcast_snapshot()
        except WebSocketDisconnect:
            pass
        finally:
            sender.cancel()
            heartbeat.cancel()
            await runtime.streams.disconnect(connection.connection_id)

    return app
