from __future__ import annotations

from datetime import timedelta

from telepathy.bus.events import make_event
from telepathy.core.models import EventType, utc_now
from telepathy.room.room import WorkspaceRoom


def test_file_lock_and_unlock(runtime) -> None:
    _, _, _, radar, bus = runtime
    bus.publish(make_event(EventType.FILE_LOCK, "a1", "x.py"))
    assert radar.get_file_status("x.py")["locked"] is True
    bus.publish(make_event(EventType.FILE_UNLOCK, "a1", "x.py"))
    assert radar.get_file_status("x.py")["locked"] is False


def test_working_event_updates_agent_task(runtime) -> None:
    _, _, _, radar, bus = runtime
    bus.publish(make_event(EventType.AGENT_WORKING, "a1", "x.py", {"task": "edit"}))
    agent = radar.get_snapshot().active_agents[0]
    assert agent["status"] == "working"
    assert agent["current_task"] == "edit"


def test_idle_clears_agent_target(runtime) -> None:
    _, _, _, radar, bus = runtime
    bus.publish(make_event(EventType.AGENT_WORKING, "a1", "x.py", {"task": "edit"}))
    bus.publish(make_event(EventType.AGENT_IDLE, "a1"))
    assert radar.get_snapshot().active_agents[0]["current_target"] is None


def test_ci_and_deploy_state(runtime) -> None:
    _, _, _, radar, bus = runtime
    bus.publish(make_event(EventType.CI_START, "a1", "feature/x", {"status": "running"}))
    bus.publish(make_event(EventType.DEPLOY_START, "a1", "svc", {"status": "in_progress"}))
    snapshot = radar.get_snapshot()
    assert snapshot.active_ci[0]["status"] == "running"
    assert snapshot.active_deployments[0]["service"] == "svc"


def test_health_alert_updates_services(runtime) -> None:
    _, _, _, radar, bus = runtime
    bus.publish(make_event(EventType.HEALTH_ALERT, "a1", "api", {"status": "degraded"}))
    assert radar.get_snapshot().system_health["services"]["api"]["status"] == "degraded"


def test_schedule_pending_is_visible(runtime) -> None:
    _, _, _, radar, bus = runtime
    bus.publish(make_event(EventType.SCHEDULE_PENDING, "a1", "deploy", {"when": "soon"}))
    assert radar.get_snapshot().pending_scheduled[0]["target"] == "deploy"


def test_mark_stale_agents_offline(runtime) -> None:
    _, room, _, radar, bus = runtime
    bus.publish(make_event(EventType.AGENT_JOIN, "a1"))
    room.agents["a1"].last_heartbeat = utc_now() - timedelta(seconds=120)
    assert room.mark_stale_agents(max_age_seconds=30) == ["a1"]
    assert radar.get_snapshot().active_agents == []


def test_room_replays_persisted_locks(db_path) -> None:
    from telepathy.core.db import TelepathyDB

    db = TelepathyDB(db_path)
    room = WorkspaceRoom(db)
    room.apply_event(make_event(EventType.FILE_LOCK, "a1", "x.py"))
    reloaded = WorkspaceRoom(db)
    assert reloaded.get_file_status("x.py")["locked"] is True
    db.close()
