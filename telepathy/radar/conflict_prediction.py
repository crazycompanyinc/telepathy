"""Predictive conflict detection."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any


def normalize_target(target: str | None) -> str:
    if not target:
        return ""
    return str(PurePosixPath(target.replace("\\", "/")))


def targets_overlap(left: str | None, right: str | None) -> bool:
    left_norm = normalize_target(left)
    right_norm = normalize_target(right)
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return True
    left_prefix = left_norm.rstrip("/") + "/"
    right_prefix = right_norm.rstrip("/") + "/"
    if left_norm.startswith(right_prefix) or right_norm.startswith(left_prefix):
        return True
    return str(PurePosixPath(left_norm).parent) == str(PurePosixPath(right_norm).parent)


def predict_conflicts(
    active_agents: list[dict[str, Any]],
    locked_files: list[dict[str, Any]],
    intents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []

    for intent in intents:
        actor = intent.get("agent_id")
        target = intent.get("target")
        for lock in locked_files:
            locked_by = lock.get("locked_by")
            if locked_by != actor and targets_overlap(target, lock.get("file")):
                conflicts.append(
                    {
                        "severity": "high",
                        "agents": [actor, locked_by],
                        "target": target,
                        "message": f"{actor} may conflict with {locked_by} on {target}",
                    }
                )
        for agent in active_agents:
            other = agent.get("agent_id")
            other_target = agent.get("current_target")
            if other != actor and targets_overlap(target, other_target):
                conflicts.append(
                    {
                        "severity": "medium",
                        "agents": [actor, other],
                        "target": target,
                        "message": f"{actor}'s planned work may overlap {other}'s active work on {other_target}",
                    }
                )
    return dedupe_conflicts(conflicts)


def dedupe_conflicts(conflicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict[str, Any]] = []
    for conflict in conflicts:
        agents = sorted(str(agent) for agent in conflict.get("agents", []) if agent)
        key = (",".join(agents), str(conflict.get("target")), str(conflict.get("severity")))
        if key not in seen:
            seen.add(key)
            unique.append(conflict)
    return unique
