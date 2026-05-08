"""Production workspace intelligence built on the Telepathy event stream."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4

from telepathy.core.db import TelepathyDB
from telepathy.core.models import EventType, WorkspaceEvent, utc_now
from telepathy.radar.conflict_prediction import targets_overlap
from telepathy.room.room import WorkspaceRoom


DEFAULT_ZONES = {
    "frontend": ["frontend", "web", "ui", "client", "static", "templates"],
    "backend": ["backend", "api", "server", "auth", "models", "services"],
    "infra": ["infra", "ops", ".github", "deploy", "terraform", "k8s", "docker"],
}


class WorkspaceIntelligence:
    """Derives v2 features from room state plus persisted event history."""

    def __init__(self, room: WorkspaceRoom, db: TelepathyDB | None = None, zones: dict[str, list[str]] | None = None):
        self.room = room
        self.db = db or room.db
        self.zones = zones or DEFAULT_ZONES

    def enriched_snapshot(self) -> dict[str, Any]:
        snapshot = self.room.get_snapshot().as_dict()
        events = self._events(limit=1000)
        snapshot["zones"] = self.zone_activity(events)
        snapshot["collaboration_suggestions"] = self.collaboration_suggestions(events)
        snapshot["anomalies"] = self.anomalies(events)
        snapshot["capacity"] = self.capacity()
        snapshot["deadlocks"] = self.room.detect_deadlocks()
        snapshot["integrations"] = self.integrations(events)
        snapshot["work_patterns"] = self.work_patterns(events)
        snapshot["health_score"] = self.health_score(snapshot)
        return snapshot

    def replay_for_agent(self, agent_id: str, limit: int = 200) -> dict[str, Any]:
        events = self._events(limit=limit)
        agent = self.room.agents.get(agent_id)
        return {
            "agent_id": agent_id,
            "agent": agent.model_dump(mode="json") if agent else None,
            "snapshot": self.enriched_snapshot(),
            "events": [event.model_dump(mode="json") for event in events],
            "replay_cursor": events[-1].event_id if events else None,
        }

    def zone_for_target(self, target: str | None) -> str:
        if not target:
            return "workspace"
        parts = PurePosixPath(target.replace("\\", "/")).parts
        first = parts[0] if parts else target
        for zone, prefixes in self.zones.items():
            if first in prefixes or any(str(target).startswith(prefix.rstrip("/") + "/") for prefix in prefixes):
                return zone
        return "workspace"

    def zone_activity(self, events: list[WorkspaceEvent] | None = None) -> dict[str, dict[str, Any]]:
        events = events or self._events(limit=1000)
        activity: dict[str, dict[str, Any]] = {
            zone: {"active_agents": [], "locked_files": [], "recent_events": 0, "active_intents": []}
            for zone in [*self.zones, "workspace"]
        }
        for agent in self.room.get_snapshot().active_agents:
            activity[self.zone_for_target(agent.get("current_target"))]["active_agents"].append(agent)
        for lock in self.room.locked_files.values():
            activity[self.zone_for_target(lock.get("file"))]["locked_files"].append(lock)
        for intent in self.room.get_snapshot().active_intents:
            activity[self.zone_for_target(intent.get("target"))]["active_intents"].append(intent)
        for event in events:
            activity[self.zone_for_target(event.target)]["recent_events"] += 1
        return activity

    def agent_intents(self) -> list[dict[str, Any]]:
        return self.room.get_snapshot().active_intents

    def collaboration_suggestions(self, events: list[WorkspaceEvent] | None = None) -> list[dict[str, Any]]:
        events = events or self._events(limit=1000)
        history: dict[str, set[str]] = defaultdict(set)
        for event in events:
            if event.agent_id and event.target and event.event_type in {
                EventType.FILE_CHANGE,
                EventType.FILE_LOCK,
                EventType.AGENT_WORKING,
                EventType.INTENT,
            }:
                history[event.agent_id].add(event.target)

        suggestions: list[dict[str, Any]] = []
        for agent in self.room.get_snapshot().active_agents:
            actor = agent.get("agent_id")
            target = agent.get("current_target")
            if not actor or not target:
                continue
            for other, targets in history.items():
                if other == actor:
                    continue
                if any(targets_overlap(target, previous) for previous in targets):
                    suggestions.append(
                        {
                            "type": "similar_work_history",
                            "agents": [actor, other],
                            "target": target,
                            "message": f"{actor} is working on {target}. {other} has related history; suggest collaboration.",
                        }
                    )
        return self._dedupe_by_message(suggestions)

    def anomalies(self, events: list[WorkspaceEvent] | None = None, now: datetime | None = None) -> list[dict[str, Any]]:
        events = events or self._events(limit=1000)
        now = now or utc_now()
        anomalies: list[dict[str, Any]] = []
        recent_deploys = [
            event for event in events if event.event_type == EventType.DEPLOY_START and now - event.timestamp <= timedelta(minutes=10)
        ]
        if len(recent_deploys) >= 3:
            anomalies.append(
                {
                    "severity": "high",
                    "type": "deploy_frequency",
                    "message": f"{len(recent_deploys)} deploys in 10 minutes is an unusual pattern.",
                }
            )
        for event in events:
            if event.agent_id and event.event_type in {EventType.AGENT_WORKING, EventType.DEPLOY_START}:
                if event.timestamp.hour < 6 or event.timestamp.hour >= 22:
                    anomalies.append(
                        {
                            "severity": "medium",
                            "type": "outside_normal_hours",
                            "agent_id": event.agent_id,
                            "message": f"{event.agent_id} is active outside normal hours.",
                        }
                    )
        return self._dedupe_by_message(anomalies)

    def capacity(self) -> dict[str, dict[str, Any]]:
        snapshot = self.room.get_snapshot()
        capacity: dict[str, dict[str, Any]] = {}
        for agent in self.room.agents.values():
            if agent.status == "offline":
                continue
            active_tasks = 1 if agent.current_task else 0
            active_tasks += sum(1 for lock in self.room.locked_files.values() if lock.get("locked_by") == agent.agent_id)
            active_tasks += sum(1 for item in snapshot.active_intents if item.get("agent_id") == agent.agent_id)
            active_tasks += sum(1 for item in snapshot.pending_scheduled if item.get("agent_id") == agent.agent_id)
            active_tasks += sum(1 for item in snapshot.active_ci if item.get("triggered_by") == agent.agent_id)
            active_tasks += sum(1 for item in snapshot.active_deployments if item.get("deployed_by") == agent.agent_id)
            capacity[agent.agent_id] = {
                "status": agent.status,
                "active_tasks": active_tasks,
                "load": "high" if active_tasks >= 5 else "medium" if active_tasks >= 3 else "normal",
                "recommendation": "consider load balancing" if active_tasks >= 5 else "ok",
            }
        return capacity

    def integrations(self, events: list[WorkspaceEvent] | None = None) -> dict[str, list[dict[str, Any]]]:
        events = events or self._events(limit=1000)
        data = {"agentcontract": [], "sentryagent": [], "quorum": []}
        for event in events:
            payload = event.model_dump(mode="json")
            source = str(event.data.get("source") or event.data.get("integration") or "").lower()
            if event.event_type == EventType.INTENT or source == "agentcontract":
                data["agentcontract"].append(payload)
            if event.event_type == EventType.VIOLATION or source == "sentryagent":
                data["sentryagent"].append(payload)
            if event.event_type == EventType.DISPUTE or source == "quorum":
                data["quorum"].append(payload)
        return data

    def work_patterns(self, events: list[WorkspaceEvent] | None = None) -> dict[str, dict[str, Any]]:
        events = events or self._events(limit=1000)
        by_agent: dict[str, Counter[int]] = defaultdict(Counter)
        for event in events:
            if event.agent_id and event.event_type in {EventType.AGENT_WORKING, EventType.FILE_CHANGE, EventType.CI_END}:
                by_agent[event.agent_id][event.timestamp.hour] += 1
        patterns: dict[str, dict[str, Any]] = {}
        for agent_id, hours in by_agent.items():
            if not hours:
                continue
            best_hour, count = hours.most_common(1)[0]
            patterns[agent_id] = {
                "best_window": f"{best_hour:02d}:00-{(best_hour + 3) % 24:02d}:00 UTC",
                "sample_size": sum(hours.values()),
                "confidence": "high" if count >= 5 else "medium" if count >= 2 else "low",
            }
        return patterns

    def health_score(self, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        snapshot = snapshot or self.enriched_snapshot()
        incidents = [
            service for service in snapshot.get("system_health", {}).get("services", {}).values()
            if service.get("status") not in {None, "healthy", "ok", "passed"}
        ]
        blocked = [agent for agent in snapshot.get("active_agents", []) if agent.get("status") in {"blocked", "waiting"}]
        anomalies = snapshot.get("anomalies", [])
        deadlocks = snapshot.get("deadlocks", [])
        score = 100 - (len(incidents) * 8) - (len(blocked) * 10) - (len(anomalies) * 5) - (len(deadlocks) * 20)
        score = max(0, min(100, score))
        return {
            "score": score,
            "summary": (
                f"Workspace health: {score}/100 "
                f"({len(incidents)} active incidents, {len(blocked)} blocked agents, {len(anomalies)} anomalies)."
            ),
            "active_incidents": len(incidents),
            "blocked_agents": len(blocked),
            "anomalies": len(anomalies),
            "deadlocks": len(deadlocks),
        }

    def save_snapshot(self, name: str) -> dict[str, Any]:
        if not self.db:
            raise RuntimeError("snapshot persistence requires TelepathyDB")
        created_at = utc_now().isoformat()
        snapshot_id = str(uuid4())
        payload = self.enriched_snapshot()
        self.db.save_workspace_snapshot(snapshot_id, name, payload, created_at)
        return {"snapshot_id": snapshot_id, "name": name, "created_at": created_at, "snapshot": payload}

    def list_snapshots(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.db:
            return []
        return self.db.list_workspace_snapshots(limit)

    def compare_snapshots(self, left_id: str, right_id: str) -> dict[str, Any]:
        if not self.db:
            raise RuntimeError("snapshot comparison requires TelepathyDB")
        left = self.db.get_workspace_snapshot(left_id)
        right = self.db.get_workspace_snapshot(right_id)
        if not left or not right:
            raise KeyError("snapshot not found")
        left_score = self._activity_score(left["snapshot"])
        right_score = self._activity_score(right["snapshot"])
        delta = right_score - left_score
        percent = 0 if left_score == 0 else round((delta / left_score) * 100, 2)
        return {
            "left": left_id,
            "right": right_id,
            "activity_delta": delta,
            "activity_percent_change": percent,
            "message": f"Workspace is {abs(percent)}% {'more' if percent >= 0 else 'less'} active than baseline.",
        }

    def _events(self, limit: int = 1000) -> list[WorkspaceEvent]:
        if self.db:
            return self.db.list_events(limit=limit)
        return self.room.get_recent_events()[-limit:]

    def _activity_score(self, snapshot: dict[str, Any]) -> int:
        return (
            len(snapshot.get("active_agents", [])) * 3
            + len(snapshot.get("locked_files", [])) * 2
            + len(snapshot.get("active_deployments", [])) * 4
            + len(snapshot.get("active_ci", [])) * 2
            + len(snapshot.get("recent_events", []))
            + len(snapshot.get("active_intents", [])) * 2
        )

    def _dedupe_by_message(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for item in items:
            message = str(item.get("message"))
            if message not in seen:
                seen.add(message)
                unique.append(item)
        return unique
