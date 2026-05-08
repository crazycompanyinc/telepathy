from __future__ import annotations

from telepathy.bus.events import make_event
from telepathy.core.models import EventType
from telepathy.stream.manager import StreamManager


class FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.sent = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload) -> None:
        self.sent.append(payload)


async def test_stream_connect_sends_snapshot(runtime) -> None:
    _, _, subscriptions, radar, _ = runtime
    manager = StreamManager(radar, subscriptions)
    websocket = FakeWebSocket()
    connection = await manager.connect("a1", websocket)
    assert websocket.accepted is True
    assert websocket.sent[0]["type"] == "snapshot"
    await manager.disconnect(connection.connection_id)


async def test_stream_push_filters_by_subscription(runtime) -> None:
    _, _, subscriptions, radar, _ = runtime
    subscriptions.subscribe("a1", ["file_change"], ["frontend"])
    manager = StreamManager(radar, subscriptions)
    connection = await manager.connect("a1", FakeWebSocket())
    await manager.push_event(make_event(EventType.CI_START, "a2", "main"))
    assert connection.queue.empty()
    await manager.push_event(make_event(EventType.FILE_CHANGE, "a2", "frontend/index.html"))
    assert (await connection.queue.get())["type"] == "event"
    await manager.disconnect(connection.connection_id)


async def test_stream_broadcast_snapshot_queues_payload(runtime) -> None:
    _, _, subscriptions, radar, _ = runtime
    manager = StreamManager(radar, subscriptions)
    connection = await manager.connect("a1", FakeWebSocket())
    await manager.broadcast_snapshot()
    assert (await connection.queue.get())["type"] == "snapshot"
    await manager.disconnect(connection.connection_id)
