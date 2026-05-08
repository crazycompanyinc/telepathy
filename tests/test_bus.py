from __future__ import annotations

from telepathy.bus.events import make_event
from telepathy.core.models import EventType


def test_publish_updates_snapshot(runtime) -> None:
    _, _, _, _, bus = runtime
    snapshot = bus.publish(make_event(EventType.AGENT_JOIN, agent_id="a1"))
    assert snapshot.active_agents[0]["agent_id"] == "a1"


def test_publish_notifies_subscribers(runtime) -> None:
    _, _, _, _, bus = runtime
    seen = []
    bus.subscribe("test", lambda event, snapshot: seen.append((event, snapshot)))
    bus.publish(make_event(EventType.FILE_CHANGE, agent_id="a1", target="x.py"))
    assert seen[0][0].target == "x.py"


def test_unsubscribe_stops_notifications(runtime) -> None:
    _, _, _, _, bus = runtime
    seen = []
    bus.subscribe("test", lambda event, snapshot: seen.append(event))
    bus.unsubscribe("test")
    bus.publish(make_event(EventType.FILE_CHANGE, target="x.py"))
    assert seen == []


def test_make_event_accepts_string_type() -> None:
    event = make_event("file_lock", agent_id="a1", target="x.py")
    assert event.event_type == EventType.FILE_LOCK
