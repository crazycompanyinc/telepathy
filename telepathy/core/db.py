"""SQLite persistence for Telepathy."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

from telepathy.core.models import AgentSubscription, WorkspaceAgent, WorkspaceEvent


DEFAULT_DB_PATH = Path(".telepathy/telepathy.db")


class TelepathyDB:
    """Small thread-safe SQLite repository with WAL enabled."""

    def __init__(self, path: str | Path = DEFAULT_DB_PATH):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self.init()

    def init(self) -> None:
        with self._lock, self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agents (
                    agent_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    agent_id TEXT,
                    target TEXT,
                    payload TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS subscriptions (
                    subscription_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workspace_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def upsert_agent(self, agent: WorkspaceAgent) -> None:
        payload = agent.model_dump_json()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO agents(agent_id, payload, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    payload=excluded.payload,
                    updated_at=excluded.updated_at
                """,
                (agent.agent_id, payload, agent.last_heartbeat.isoformat()),
            )

    def get_agent(self, agent_id: str) -> WorkspaceAgent | None:
        with self._lock:
            row = self._conn.execute("SELECT payload FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
        return WorkspaceAgent.model_validate_json(row["payload"]) if row else None

    def list_agents(self) -> list[WorkspaceAgent]:
        with self._lock:
            rows = self._conn.execute("SELECT payload FROM agents ORDER BY agent_id").fetchall()
        return [WorkspaceAgent.model_validate_json(row["payload"]) for row in rows]

    def append_event(self, event: WorkspaceEvent) -> None:
        payload = event.model_dump_json()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO events(event_id, event_type, agent_id, target, payload, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.event_type.value,
                    event.agent_id,
                    event.target,
                    payload,
                    event.timestamp.isoformat(),
                ),
            )

    def list_events(self, limit: int = 20) -> list[WorkspaceEvent]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload FROM events ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        return [WorkspaceEvent.model_validate_json(row["payload"]) for row in reversed(rows)]

    def save_workspace_snapshot(self, snapshot_id: str, name: str, payload: dict[str, Any], created_at: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO workspace_snapshots(snapshot_id, name, payload, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (snapshot_id, name, json.dumps(payload), created_at),
            )

    def get_workspace_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT snapshot_id, name, payload, created_at FROM workspace_snapshots WHERE snapshot_id=?",
                (snapshot_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "snapshot_id": row["snapshot_id"],
            "name": row["name"],
            "created_at": row["created_at"],
            "snapshot": json.loads(row["payload"]),
        }

    def list_workspace_snapshots(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT snapshot_id, name, payload, created_at
                FROM workspace_snapshots
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "snapshot_id": row["snapshot_id"],
                "name": row["name"],
                "created_at": row["created_at"],
                "snapshot": json.loads(row["payload"]),
            }
            for row in rows
        ]

    def save_subscription(self, subscription: AgentSubscription) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO subscriptions(subscription_id, agent_id, payload, created_at) VALUES (?, ?, ?, ?)",
                (
                    subscription.subscription_id,
                    subscription.agent_id,
                    subscription.model_dump_json(),
                    subscription.created_at.isoformat(),
                ),
            )

    def list_subscriptions(self, agent_id: str | None = None) -> list[AgentSubscription]:
        sql = "SELECT payload FROM subscriptions"
        args: Iterable[str] = ()
        if agent_id:
            sql += " WHERE agent_id=?"
            args = (agent_id,)
        with self._lock:
            rows = self._conn.execute(sql, tuple(args)).fetchall()
        return [AgentSubscription.model_validate_json(row["payload"]) for row in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
