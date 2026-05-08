from __future__ import annotations

from telepathy.bus.events import make_event
from telepathy.core.models import EventType
from telepathy.radar.conflict_prediction import targets_overlap


def test_targets_overlap_exact_and_directory() -> None:
    assert targets_overlap("frontend/api.js", "frontend")
    assert targets_overlap("x.py", "x.py")
    assert targets_overlap("frontend/api.js", "frontend/index.html")
    assert not targets_overlap("frontend/api.js", "auth")


def test_intent_predicts_lock_conflict(runtime) -> None:
    _, _, _, radar, bus = runtime
    bus.publish(make_event(EventType.FILE_LOCK, "a1", "frontend/index.html"))
    bus.publish(make_event(EventType.INTENT, "a2", "frontend/index.html"))
    conflicts = radar.get_predicted_conflicts()
    assert conflicts
    assert conflicts[0]["severity"] == "high"


def test_intent_predicts_nearby_agent_conflict(runtime) -> None:
    _, _, _, radar, bus = runtime
    bus.publish(make_event(EventType.AGENT_WORKING, "a1", "frontend", {"task": "edit"}))
    bus.publish(make_event(EventType.INTENT, "a2", "frontend/api.js"))
    assert radar.get_predicted_conflicts()[0]["severity"] == "medium"


def test_agent_view_filters_recent_events(runtime) -> None:
    _, _, subscriptions, radar, bus = runtime
    subscriptions.subscribe("a1", ["file_change"], ["frontend"])
    bus.publish(make_event(EventType.FILE_CHANGE, "a2", "frontend/index.html"))
    bus.publish(make_event(EventType.CI_START, "a2", "main"))
    view = radar.get_agent_view("a1")
    assert len(view["recent_events"]) == 1
    assert view["recent_events"][0]["event_type"] == "file_change"


def test_recent_events_filter(runtime) -> None:
    _, _, _, radar, bus = runtime
    bus.publish(make_event(EventType.FILE_CHANGE, "a1", "x.py"))
    bus.publish(make_event(EventType.CI_START, "a1", "main"))
    assert len(radar.get_recent_events(event_type="file_change")) == 1
