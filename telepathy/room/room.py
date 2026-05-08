"""Thread-safe shared workspace state."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from telepathy.core.db import TelepathyDB
from telepathy.core.models import EventType, WorkspaceAgent, WorkspaceEvent, WorkspaceSnapshot, utc_now
from telepathy.radar.conflict_prediction import predict_conflicts, targets_overlap


class WorkspaceRoom:
    """Owns the live workspace snapshot and applies events to it."""

    def __init__(self, db: TelepathyDB | None = None):
        self.db = db
        self._lock = threading.RLock()
        self.agents: dict[str, WorkspaceAgent] = {}
        self.locked_files: dict[str, dict[str, Any]] = {}
        self.active_deployments: dict[str, dict[str, Any]] = {}
        self.active_ci: dict[str, dict[str, Any]] = {}
        self.system_health: dict[str, Any] = {"services": {}}
        self.pending_scheduled: list[dict[str, Any]] = []
        self.recent_events: list[WorkspaceEvent] = []
        self.intents: list[dict[str, Any]] = []
        if db:
            self.load_from_db()

    def load_from_db(self) -> None:
        if not self.db:
            return
        with self._lock:
            self.agents = {agent.agent_id: agent for agent in self.db.list_agents()}
            for event in self.db.list_events(limit=1000):
                self._remember_event(event)
                handler = getattr(self, f"_apply_{event.event_type.value}", None)
                if handler:
                    handler(event)

    def register_agent(self, agent_id: str, agent_name: str | None = None, agent_type: str = "agent") -> WorkspaceAgent:
        with self._lock:
            agent = self.agents.get(agent_id) or WorkspaceAgent(
                agent_id=agent_id,
                agent_name=agent_name or agent_id,
                agent_type=agent_type,
            )
            agent.agent_name = agent_name or agent.agent_name or agent_id
            agent.agent_type = agent_type or agent.agent_type
            agent.last_heartbeat = utc_now()
            self.agents[agent_id] = agent
            if self.db:
                self.db.upsert_agent(agent)
            return agent

    def apply_event(self, event: WorkspaceEvent) -> WorkspaceSnapshot:
        with self._lock:
            self._remember_event(event)
            if event.agent_id and event.agent_id not in self.agents:
                self.register_agent(event.agent_id)
            handler = getattr(self, f"_apply_{event.event_type.value}", None)
            if handler:
                handler(event)
            if self.db:
                self.db.append_event(event)
            return self.get_snapshot()

    def heartbeat(self, agent_id: str) -> None:
        with self._lock:
            agent = self.agents.get(agent_id)
            if agent:
                agent.last_heartbeat = utc_now()
                if self.db:
                    self.db.upsert_agent(agent)

    def mark_stale_agents(self, max_age_seconds: int = 90) -> list[str]:
        cutoff = utc_now() - timedelta(seconds=max_age_seconds)
        stale: list[str] = []
        with self._lock:
            for agent in self.agents.values():
                if agent.status != "offline" and agent.last_heartbeat < cutoff:
                    agent.status = "offline"
                    stale.append(agent.agent_id)
                    if self.db:
                        self.db.upsert_agent(agent)
        return stale

    def get_snapshot(self) -> WorkspaceSnapshot:
        with self._lock:
            active_agents = [
                {
                    "agent_id": agent.agent_id,
                    "agent_name": agent.agent_name,
                    "agent_type": agent.agent_type,
                    "status": agent.status,
                    "current_task": agent.current_task,
                    "current_target": agent.current_target,
                    "last_heartbeat": agent.last_heartbeat.isoformat(),
                }
                for agent in self.agents.values()
                if agent.status != "offline"
            ]
            locked_files = list(self.locked_files.values())
            conflicts = predict_conflicts(active_agents, locked_files, self._active_intents())
            return WorkspaceSnapshot(
                active_agents=active_agents,
                locked_files=locked_files,
                active_deployments=list(self.active_deployments.values()),
                active_ci=list(self.active_ci.values()),
                recent_events=[event.model_dump(mode="json") for event in self.recent_events[-20:]],
                system_health=self.system_health,
                pending_scheduled=list(self.pending_scheduled),
                predicted_conflicts=conflicts,
                updated_at=utc_now(),
            )

    def get_file_status(self, path: str) -> dict[str, Any]:
        with self._lock:
            lock = self.locked_files.get(path)
            users = [
                {"agent_id": agent.agent_id, "status": agent.status, "current_task": agent.current_task}
                for agent in self.agents.values()
                if targets_overlap(path, agent.current_target)
            ]
            return {"path": path, "locked": bool(lock), "lock": lock, "active_users": users}

    def get_recent_events(self, event_type: str | None = None, target: str | None = None) -> list[WorkspaceEvent]:
        with self._lock:
            events = list(self.recent_events)
        if event_type:
            events = [event for event in events if event.event_type.value == event_type]
        if target:
            events = [event for event in events if targets_overlap(event.target, target)]
        return events

    def _remember_event(self, event: WorkspaceEvent) -> None:
        self.recent_events.append(event)
        self.recent_events = self.recent_events[-20:]

    def _agent(self, event: WorkspaceEvent) -> WorkspaceAgent | None:
        return self.agents.get(event.agent_id or "")

    def _set_agent_status(self, event: WorkspaceEvent, status: str) -> None:
        agent = self._agent(event)
        if not agent:
            return
        agent.status = status  # type: ignore[assignment]
        agent.last_heartbeat = utc_now()
        if "task" in event.data:
            agent.current_task = event.data["task"]
        if event.target:
            agent.current_target = event.target
        if status in {"idle", "offline"}:
            agent.current_task = None
            agent.current_target = None
        if self.db:
            self.db.upsert_agent(agent)

    def _apply_agent_join(self, event: WorkspaceEvent) -> None:
        self._set_agent_status(event, "idle")

    def _apply_agent_start(self, event: WorkspaceEvent) -> None:
        self._apply_agent_join(event)

    def _apply_agent_leave(self, event: WorkspaceEvent) -> None:
        self._set_agent_status(event, "offline")

    def _apply_agent_stop(self, event: WorkspaceEvent) -> None:
        self._apply_agent_leave(event)

    def _apply_agent_working(self, event: WorkspaceEvent) -> None:
        self._set_agent_status(event, "working")

    def _apply_agent_idle(self, event: WorkspaceEvent) -> None:
        self._set_agent_status(event, "idle")

    def _apply_agent_blocked(self, event: WorkspaceEvent) -> None:
        self._set_agent_status(event, "blocked")

    def _apply_file_lock(self, event: WorkspaceEvent) -> None:
        if event.target:
            self.locked_files[event.target] = {
                "file": event.target,
                "locked_by": event.agent_id,
                "since": event.timestamp.isoformat(),
                "until": event.data.get("until"),
            }

    def _apply_file_unlock(self, event: WorkspaceEvent) -> None:
        if event.target:
            self.locked_files.pop(event.target, None)

    def _apply_deploy_start(self, event: WorkspaceEvent) -> None:
        service = event.target or event.data.get("service", "unknown")
        self.active_deployments[service] = {
            "service": service,
            "deployed_by": event.agent_id,
            "started_at": event.timestamp.isoformat(),
            "status": event.data.get("status", "in_progress"),
            **event.data,
        }

    def _apply_deploy_end(self, event: WorkspaceEvent) -> None:
        service = event.target or event.data.get("service", "unknown")
        deployment = self.active_deployments.get(service, {"service": service, "deployed_by": event.agent_id})
        deployment.update(event.data)
        deployment["status"] = event.data.get("status", "complete")
        deployment["ended_at"] = event.timestamp.isoformat()
        self.active_deployments[service] = deployment

    def _apply_ci_start(self, event: WorkspaceEvent) -> None:
        branch = event.target or event.data.get("branch", "unknown")
        self.active_ci[branch] = {
            "branch": branch,
            "triggered_by": event.agent_id,
            "started_at": event.timestamp.isoformat(),
            "status": event.data.get("status", "running"),
            **event.data,
        }

    def _apply_ci_end(self, event: WorkspaceEvent) -> None:
        branch = event.target or event.data.get("branch", "unknown")
        ci = self.active_ci.get(branch, {"branch": branch, "triggered_by": event.agent_id})
        ci.update(event.data)
        ci["status"] = event.data.get("status", "passed")
        ci["ended_at"] = event.timestamp.isoformat()
        self.active_ci[branch] = ci

    def _apply_system_health(self, event: WorkspaceEvent) -> None:
        self._update_health(event)

    def _apply_health_alert(self, event: WorkspaceEvent) -> None:
        self._update_health(event)

    def _update_health(self, event: WorkspaceEvent) -> None:
        service = event.target or event.data.get("service", "system")
        self.system_health.setdefault("services", {})[service] = {
            "status": event.data.get("status", "unknown"),
            "updated_at": event.timestamp.isoformat(),
            **event.data,
        }

    def _apply_schedule(self, event: WorkspaceEvent) -> None:
        self._apply_schedule_pending(event)

    def _apply_schedule_pending(self, event: WorkspaceEvent) -> None:
        self.pending_scheduled.append({"target": event.target, "agent_id": event.agent_id, **event.data})
        self.pending_scheduled = self.pending_scheduled[-20:]

    def _apply_intent(self, event: WorkspaceEvent) -> None:
        self.intents.append({"agent_id": event.agent_id, "target": event.target, "timestamp": event.timestamp, **event.data})
        self.intents = self.intents[-50:]

    def _active_intents(self) -> list[dict[str, Any]]:
        now = utc_now()
        return [
            intent
            for intent in self.intents
            if isinstance(intent.get("timestamp"), datetime)
            and now - intent["timestamp"] < timedelta(seconds=int(intent.get("ttl", 300)))
        ]
