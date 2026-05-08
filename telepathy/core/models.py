"""Typed models for Telepathy workspace state."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""
    return datetime.now(timezone.utc)


AgentStatus = Literal["idle", "working", "waiting", "blocked", "offline"]


class EventType(StrEnum):
    FILE_LOCK = "file_lock"
    FILE_UNLOCK = "file_unlock"
    FILE_CHANGE = "file_change"
    DEPLOY_START = "deploy_start"
    DEPLOY_END = "deploy_end"
    CI_START = "ci_start"
    CI_END = "ci_end"
    AGENT_START = "agent_start"
    AGENT_STOP = "agent_stop"
    AGENT_JOIN = "agent_join"
    AGENT_LEAVE = "agent_leave"
    AGENT_WORKING = "agent_working"
    AGENT_IDLE = "agent_idle"
    AGENT_BLOCKED = "agent_blocked"
    SYSTEM_HEALTH = "system_health"
    HEALTH_ALERT = "health_alert"
    SCHEDULE = "schedule"
    SCHEDULE_PENDING = "schedule_pending"
    INTENT = "intent"


class WorkspaceAgent(BaseModel):
    agent_id: str
    agent_name: str | None = None
    agent_type: str = "agent"
    status: AgentStatus = "offline"
    current_task: str | None = None
    current_target: str | None = None
    last_heartbeat: datetime = Field(default_factory=utc_now)
    registered_at: datetime = Field(default_factory=utc_now)


class WorkspaceEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: EventType
    agent_id: str | None = None
    target: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utc_now)
    ttl: int = 300


class AgentSubscription(BaseModel):
    subscription_id: str = Field(default_factory=lambda: str(uuid4()))
    agent_id: str
    event_types: list[EventType] = Field(default_factory=list)
    targets: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class AgentPresence(BaseModel):
    agent_id: str
    is_online: bool = False
    last_seen: datetime = Field(default_factory=utc_now)
    working_on: str | None = None
    activity_log: list[dict[str, Any]] = Field(default_factory=list)


class WorkspaceSnapshot(BaseModel):
    active_agents: list[dict[str, Any]] = Field(default_factory=list)
    locked_files: list[dict[str, Any]] = Field(default_factory=list)
    active_deployments: list[dict[str, Any]] = Field(default_factory=list)
    active_ci: list[dict[str, Any]] = Field(default_factory=list)
    recent_events: list[dict[str, Any]] = Field(default_factory=list)
    system_health: dict[str, Any] = Field(default_factory=lambda: {"services": {}})
    pending_scheduled: list[dict[str, Any]] = Field(default_factory=list)
    predicted_conflicts: list[dict[str, Any]] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utc_now)

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
