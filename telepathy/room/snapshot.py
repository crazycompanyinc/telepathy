"""Snapshot serialization helpers."""

from __future__ import annotations

from telepathy.core.models import WorkspaceSnapshot


def empty_snapshot() -> WorkspaceSnapshot:
    return WorkspaceSnapshot()
