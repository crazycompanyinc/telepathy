from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from telepathy.bus.bus import EventBus
from telepathy.core.db import TelepathyDB
from telepathy.radar.engine import RadarEngine
from telepathy.room.room import WorkspaceRoom
from telepathy.subscriptions.subscriptions import SubscriptionManager


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "telepathy.db"


@pytest.fixture()
def runtime(db_path: Path):
    db = TelepathyDB(db_path)
    room = WorkspaceRoom(db)
    subscriptions = SubscriptionManager(db)
    radar = RadarEngine(room, subscriptions)
    bus = EventBus(room, subscriptions)
    yield db, room, subscriptions, radar, bus
    db.close()


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()
