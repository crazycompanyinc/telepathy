from __future__ import annotations

from datetime import timedelta

from telepathy.bus.events import make_event
from telepathy.core.models import EventType, utc_now
from telepathy.v2 import WorkspaceIntelligence


def test_persistent_replay_restores_agent_state(db_path) -> None:
    from telepathy.core.db import TelepathyDB
    from telepathy.room.room import WorkspaceRoom

    db = TelepathyDB(db_path)
    room = WorkspaceRoom(db)
    room.apply_event(make_event(EventType.AGENT_WORKING, "alpha", "backend/auth.py", {"task": "jwt"}))

    reloaded = WorkspaceRoom(db)
    replay = WorkspaceIntelligence(reloaded, db).replay_for_agent("alpha")
    assert replay["snapshot"]["active_agents"][0]["current_target"] == "backend/auth.py"
    assert replay["events"][0]["event_type"] == "agent_working"
    db.close()


def test_zone_activity_and_semantic_intents(runtime) -> None:
    _, room, _, _, bus = runtime
    bus.publish(make_event(EventType.AGENT_WORKING, "alpha", "frontend/app.tsx", {"task": "edit UI"}))
    bus.publish(
        make_event(
            EventType.INTENT,
            "alpha",
            "backend/auth.py",
            {"intent": "refactoring auth to use JWT", "ttl": 300},
        )
    )

    intelligence = WorkspaceIntelligence(room)
    zones = intelligence.zone_activity()
    intents = intelligence.agent_intents()
    assert zones["frontend"]["active_agents"][0]["agent_id"] == "alpha"
    assert "auth" in intents[0]["semantic_tags"]
    assert "refactor" in intents[0]["semantic_tags"]


def test_collaboration_suggestions_use_history(runtime) -> None:
    _, room, _, _, bus = runtime
    bus.publish(make_event(EventType.FILE_CHANGE, "beta", "auth/tokens.py"))
    bus.publish(make_event(EventType.AGENT_WORKING, "alpha", "auth/tokens.py", {"task": "rotate tokens"}))

    suggestions = WorkspaceIntelligence(room).collaboration_suggestions()
    assert suggestions[0]["agents"] == ["alpha", "beta"]


def test_anomalies_capacity_deadlocks_and_health(runtime) -> None:
    _, room, _, _, bus = runtime
    now = utc_now()
    for index in range(3):
        event = make_event(EventType.DEPLOY_START, "alpha", f"svc-{index}")
        event.timestamp = now - timedelta(minutes=index)
        bus.publish(event)
    bus.publish(make_event(EventType.AGENT_BLOCKED, "alpha", "a.py", {"waiting_for": "beta", "task": "wait beta"}))
    bus.publish(make_event(EventType.AGENT_BLOCKED, "beta", "b.py", {"waiting_for": "alpha", "task": "wait alpha"}))
    bus.publish(make_event(EventType.FILE_LOCK, "alpha", "one.py"))
    bus.publish(make_event(EventType.FILE_LOCK, "alpha", "two.py"))
    bus.publish(make_event(EventType.INTENT, "alpha", "three.py", {"intent": "change three"}))

    intelligence = WorkspaceIntelligence(room)
    assert any(item["type"] == "deploy_frequency" for item in intelligence.anomalies())
    assert intelligence.capacity()["alpha"]["load"] == "high"
    assert intelligence.room.detect_deadlocks()[0]["severity"] == "critical"
    assert intelligence.health_score(intelligence.enriched_snapshot())["score"] < 100


def test_snapshots_compare_and_integrations(runtime) -> None:
    _, room, _, _, bus = runtime
    intelligence = WorkspaceIntelligence(room)
    first = intelligence.save_snapshot("baseline")
    bus.publish(make_event(EventType.INTENT, "alpha", "api/contracts.py", {"source": "AgentContract"}))
    bus.publish(make_event(EventType.VIOLATION, "sentry", "api", {"source": "SentryAgent"}))
    bus.publish(make_event(EventType.DISPUTE, "quorum", "deploy", {"source": "Quorum"}))
    second = intelligence.save_snapshot("active")

    comparison = intelligence.compare_snapshots(first["snapshot_id"], second["snapshot_id"])
    integrations = intelligence.integrations()
    assert comparison["activity_delta"] > 0
    assert integrations["agentcontract"]
    assert integrations["sentryagent"]
    assert integrations["quorum"]


def test_work_patterns_find_best_window(runtime) -> None:
    _, room, _, _, bus = runtime
    for _ in range(3):
        event = make_event(EventType.FILE_CHANGE, "alpha", "backend/auth.py")
        event.timestamp = event.timestamp.replace(hour=9)
        bus.publish(event)

    assert WorkspaceIntelligence(room).work_patterns()["alpha"]["best_window"] == "09:00-12:00 UTC"
