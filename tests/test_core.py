from __future__ import annotations

from telepathy.core.db import TelepathyDB
from telepathy.core.models import EventType, WorkspaceAgent, WorkspaceEvent


def test_agent_defaults_are_offline() -> None:
    agent = WorkspaceAgent(agent_id="a1")
    assert agent.status == "offline"
    assert agent.agent_type == "agent"


def test_event_defaults_include_ttl_and_id() -> None:
    event = WorkspaceEvent(event_type=EventType.FILE_CHANGE)
    assert event.event_id
    assert event.ttl == 300


def test_db_persists_agents(db_path) -> None:
    db = TelepathyDB(db_path)
    db.upsert_agent(WorkspaceAgent(agent_id="a1", status="idle"))
    assert db.get_agent("a1").status == "idle"
    db.close()


def test_db_persists_events(db_path) -> None:
    db = TelepathyDB(db_path)
    db.append_event(WorkspaceEvent(event_type=EventType.CI_START, target="main"))
    assert db.list_events()[0].event_type == EventType.CI_START
    db.close()


def test_db_persists_subscriptions(runtime) -> None:
    _, _, subscriptions, _, _ = runtime
    subscriptions.subscribe("a1", ["file_change"], ["src"])
    assert subscriptions.subscriptions_for("a1")[0].targets == ["src"]
