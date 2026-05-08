"""Event helpers."""

from __future__ import annotations

from typing import Any

from telepathy.core.models import EventType, WorkspaceEvent


def make_event(
    event_type: EventType | str,
    agent_id: str | None = None,
    target: str | None = None,
    data: dict[str, Any] | None = None,
    ttl: int = 300,
) -> WorkspaceEvent:
    return WorkspaceEvent(
        event_type=EventType(event_type),
        agent_id=agent_id,
        target=target,
        data=data or {},
        ttl=ttl,
    )
