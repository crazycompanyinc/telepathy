"""Command line interface for Telepathy."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import click
import uvicorn

from telepathy.bus.bus import EventBus
from telepathy.bus.events import make_event
from telepathy.core.db import DEFAULT_DB_PATH, TelepathyDB
from telepathy.core.models import EventType
from telepathy.radar.engine import RadarEngine
from telepathy.room.room import WorkspaceRoom
from telepathy.server.app import create_app
from telepathy.subscriptions.subscriptions import SubscriptionManager
from telepathy.v2 import WorkspaceIntelligence


def build_runtime(db_path: str | Path = DEFAULT_DB_PATH) -> tuple[TelepathyDB, WorkspaceRoom, SubscriptionManager, RadarEngine, EventBus]:
    db = TelepathyDB(db_path)
    room = WorkspaceRoom(db)
    subscriptions = SubscriptionManager(db)
    radar = RadarEngine(room, subscriptions)
    bus = EventBus(room, subscriptions)
    return db, room, subscriptions, radar, bus


def print_json(data: Any) -> None:
    click.echo(json.dumps(data, indent=2, sort_keys=True))


def print_radar(snapshot: dict[str, Any]) -> None:
    agents = snapshot["active_agents"]
    locks = snapshot["locked_files"]
    deployments = snapshot["active_deployments"]
    ci = snapshot["active_ci"]
    health = snapshot["system_health"].get("services", {})
    conflicts = snapshot.get("predicted_conflicts", [])
    click.echo("")
    click.echo("RADAR")
    click.echo(f"  Agents: {len(agents)} online")
    for agent in agents:
        target = f" -> {agent['current_target']}" if agent.get("current_target") else ""
        task = f" ({agent['current_task']})" if agent.get("current_task") else ""
        click.echo(f"    {agent['agent_id']}: {agent['status'].upper()}{target}{task}")
    click.echo(f"  Locks: {len(locks)}")
    for lock in locks:
        click.echo(f"    {lock['file']} locked by {lock['locked_by']}")
    ci_text = ", ".join(f"{item['branch']}={item['status']}" for item in ci) or "none"
    deploy_text = ", ".join(f"{item['service']}={item['status']}" for item in deployments) or "none"
    health_text = ", ".join(f"{name}={value.get('status')}" for name, value in health.items()) or "ok"
    click.echo(f"  CI: {ci_text}")
    click.echo(f"  Deploys: {deploy_text}")
    click.echo(f"  Health: {health_text}")
    if conflicts:
        click.echo("  Conflicts:")
        for conflict in conflicts:
            click.echo(f"    {conflict['severity'].upper()}: {conflict['message']}")


@click.group()
def cli() -> None:
    """Telepathy real-time agent workspace awareness."""


@cli.command()
def init() -> None:
    """Initialize telepathy."""
    db = TelepathyDB(DEFAULT_DB_PATH)
    db.close()
    click.echo(f"Initialized Telepathy at {DEFAULT_DB_PATH}")


@cli.command()
@click.argument("agent_id")
@click.option("--name", "agent_name", default=None)
@click.option("--type", "agent_type", default="agent")
def register(agent_id: str, agent_name: str | None, agent_type: str) -> None:
    """Register agent in workspace."""
    db, room, *_ = build_runtime()
    agent = room.register_agent(agent_id, agent_name, agent_type)
    db.close()
    print_json(agent.model_dump(mode="json"))


@cli.command()
@click.argument("agent_id")
def join(agent_id: str) -> None:
    """Agent joins workspace."""
    db, _, _, _, bus = build_runtime()
    snapshot = bus.publish(make_event(EventType.AGENT_JOIN, agent_id=agent_id))
    db.close()
    print_radar(snapshot.as_dict())


@cli.command()
@click.argument("agent_id")
def leave(agent_id: str) -> None:
    """Agent leaves workspace."""
    db, _, _, _, bus = build_runtime()
    snapshot = bus.publish(make_event(EventType.AGENT_LEAVE, agent_id=agent_id))
    db.close()
    print_radar(snapshot.as_dict())


@cli.command()
@click.argument("agent_id")
@click.option("--target", required=True)
@click.option("--task", required=True)
def work(agent_id: str, target: str, task: str) -> None:
    """Agent starts working."""
    db, _, _, _, bus = build_runtime()
    snapshot = bus.publish(make_event(EventType.AGENT_WORKING, agent_id=agent_id, target=target, data={"task": task}))
    db.close()
    print_radar(snapshot.as_dict())


@cli.command()
@click.argument("agent_id")
def idle(agent_id: str) -> None:
    """Agent goes idle."""
    db, _, _, _, bus = build_runtime()
    snapshot = bus.publish(make_event(EventType.AGENT_IDLE, agent_id=agent_id))
    db.close()
    print_radar(snapshot.as_dict())


@cli.command("lock")
@click.argument("agent_id")
@click.option("--file", "file_path", required=True)
def lock_file(agent_id: str, file_path: str) -> None:
    """Lock a file."""
    db, _, _, _, bus = build_runtime()
    snapshot = bus.publish(make_event(EventType.FILE_LOCK, agent_id=agent_id, target=file_path))
    db.close()
    print_radar(snapshot.as_dict())


@cli.command("unlock")
@click.argument("agent_id")
@click.option("--file", "file_path", required=True)
def unlock_file(agent_id: str, file_path: str) -> None:
    """Unlock a file."""
    db, _, _, _, bus = build_runtime()
    snapshot = bus.publish(make_event(EventType.FILE_UNLOCK, agent_id=agent_id, target=file_path))
    db.close()
    print_radar(snapshot.as_dict())


@cli.command()
@click.option("--agent", "agent_id", default=None)
def radar(agent_id: str | None) -> None:
    """Show the full workspace radar."""
    db, _, _, engine, _ = build_runtime()
    data = engine.get_agent_view(agent_id) if agent_id else engine.get_snapshot().as_dict()
    db.close()
    print_radar(data)
    print_json(data)


@cli.command()
def events() -> None:
    """Show recent events."""
    db, _, _, engine, _ = build_runtime()
    print_json(engine.get_recent_events())
    db.close()


@cli.command()
def conflicts() -> None:
    """Show predicted conflicts."""
    db, _, _, engine, _ = build_runtime()
    print_json(engine.get_predicted_conflicts())
    db.close()


@cli.command()
@click.option("--seconds", default=30, show_default=True)
def watch(seconds: int) -> None:
    """Real-time watch mode."""
    end = time.time() + seconds
    while time.time() < end:
        db, _, _, engine, _ = build_runtime()
        click.clear()
        print_radar(engine.get_snapshot().as_dict())
        db.close()
        time.sleep(1)


@cli.command()
@click.option("--port", default=8000, show_default=True)
@click.option("--host", default="127.0.0.1", show_default=True)
def serve(port: int, host: str) -> None:
    """Start WebSocket server."""
    uvicorn.run(create_app(DEFAULT_DB_PATH), host=host, port=port)


@cli.command()
def demo() -> None:
    """Full multi-agent demo with live updates."""
    db = TelepathyDB(":memory:")
    room = WorkspaceRoom(db)
    subscriptions = SubscriptionManager(db)
    radar_engine = RadarEngine(room, subscriptions)
    bus = EventBus(room, subscriptions)
    intelligence = WorkspaceIntelligence(room, db)
    summary: list[str] = []

    def step(label: str, event_type: EventType, agent_id: str | None = None, target: str | None = None, data: dict[str, Any] | None = None, delay: float = 0.2) -> None:
        click.echo("")
        click.echo(label)
        snapshot = bus.publish(make_event(event_type, agent_id=agent_id, target=target, data=data or {}))
        summary.append(f"{label}: {event_type.value} {target or ''}".strip())
        print_radar(snapshot.as_dict())
        time.sleep(delay)

    click.echo("Telepathy live workspace demo")
    for agent in ["Felix-CTO", "Felix-Jim", "Agent-Alpha"]:
        room.register_agent(agent, agent)
        step(f"T+0:00 - {agent} joins workspace", EventType.AGENT_JOIN, agent)

    step("T+0:30 - Felix-Jim starts redesigning hero section", EventType.AGENT_WORKING, "Felix-Jim", "frontend/index.html", {"task": "Redesigning hero section"})
    step("T+0:30 - Felix-Jim locks frontend/index.html", EventType.FILE_LOCK, "Felix-Jim", "frontend/index.html")
    step("T+1:00 - Agent-Alpha updates token validation", EventType.AGENT_WORKING, "Agent-Alpha", "auth/middleware.py", {"task": "Updating token validation"})
    step("T+1:00 - Agent-Alpha locks auth/middleware.py", EventType.FILE_LOCK, "Agent-Alpha", "auth/middleware.py")
    step("T+1:30 - CI starts for feature/auth-v2", EventType.CI_START, "Agent-Alpha", "feature/auth-v2", {"branch": "feature/auth-v2", "status": "running"})
    step("T+2:00 - Felix-CTO refines system design", EventType.AGENT_WORKING, "Felix-CTO", "architecture/v2.md", {"task": "Refining system design"})
    step(
        "T+2:30 - Agent-Alpha broadcasts JWT refactor intent",
        EventType.INTENT,
        "Agent-Alpha",
        "backend/auth/tokens.py",
        {"intent": "refactoring auth to use JWT", "source": "AgentContract", "ttl": 300},
    )
    step("T+3:00 - CI passes", EventType.CI_END, "Agent-Alpha", "feature/auth-v2", {"branch": "feature/auth-v2", "status": "passed", "tests": 47, "failures": 0})
    step("T+3:30 - Deploy starts for auth-service v2.3", EventType.DEPLOY_START, "Agent-Alpha", "auth-service", {"version": "v2.3", "status": "in_progress"})
    step("T+4:00 - auth-service health degraded", EventType.HEALTH_ALERT, "Agent-Alpha", "auth-service", {"status": "degraded", "detail": "some 503s"})
    step("T+4:05 - SentryAgent reports contract violation", EventType.VIOLATION, "SentryAgent", "auth-service", {"source": "SentryAgent", "rule": "error-budget"})
    step("T+4:10 - Quorum opens rollback dispute", EventType.DISPUTE, "Quorum", "auth-service", {"source": "Quorum", "topic": "rollback auth-service"})
    step("T+4:30 - Agent-Alpha rolls back auth-service", EventType.DEPLOY_END, "Agent-Alpha", "auth-service", {"version": "v2.2", "status": "rolled_back"})
    step("T+4:30 - auth-service recovering", EventType.SYSTEM_HEALTH, "Agent-Alpha", "auth-service", {"status": "recovering"})
    step("T+5:00 - auth-service healthy", EventType.SYSTEM_HEALTH, "Agent-Alpha", "auth-service", {"status": "healthy"})
    step("T+5:00 - Agent-Alpha unlocks auth/middleware.py", EventType.FILE_UNLOCK, "Agent-Alpha", "auth/middleware.py")
    step("T+5:00 - Agent-Alpha goes idle", EventType.AGENT_IDLE, "Agent-Alpha")
    step("T+5:00 - Felix-Jim unlocks frontend/index.html", EventType.FILE_UNLOCK, "Felix-Jim", "frontend/index.html")
    step("T+5:00 - Felix-Jim goes idle", EventType.AGENT_IDLE, "Felix-Jim")

    click.echo("")
    click.echo("Late joiner receives full recent history:")
    room.register_agent("Late-Agent", "Late-Agent")
    late_view = radar_engine.get_agent_view("Late-Agent")
    replay = intelligence.replay_for_agent("Late-Agent")
    click.echo(f"  recent_events={len(late_view['recent_events'])} replay_events={len(replay['events'])}")
    print_radar(late_view)
    enriched = intelligence.enriched_snapshot()
    click.echo("")
    click.echo("v2.0 intelligence")
    click.echo(f"  health={enriched['health_score']['summary']}")
    click.echo(f"  zones={', '.join(zone for zone, data in enriched['zones'].items() if data['recent_events'])}")
    click.echo(f"  suggestions={len(enriched['collaboration_suggestions'])}")
    click.echo(f"  anomalies={len(enriched['anomalies'])}")
    click.echo(f"  integrations={', '.join(name for name, items in enriched['integrations'].items() if items)}")
    click.echo("")
    click.echo("Session summary")
    for item in summary:
        click.echo(f"  - {item}")
    db.close()


if __name__ == "__main__":
    cli()
