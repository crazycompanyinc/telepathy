from __future__ import annotations

import inspect

from click.testing import CliRunner

from telepathy.cli import cli
from telepathy.server.app import create_app


def endpoint(app, path: str):
    return next(route.endpoint for route in app.routes if getattr(route, "path", None) == path)


async def call(func, *args):
    result = func(*args)
    if inspect.isawaitable(result):
        return await result
    return result


async def test_api_register_join_work_and_radar(tmp_path) -> None:
    app = create_app(tmp_path / "api.db")
    await call(endpoint(app, "/agents"), {"agent_id": "a1"})
    await call(endpoint(app, "/agents/{agent_id}/join"), "a1")
    await call(endpoint(app, "/agents/{agent_id}/work"), "a1", {"target": "x.py", "task": "edit"})
    radar = await call(endpoint(app, "/radar"))
    assert radar["active_agents"][0]["current_target"] == "x.py"


async def test_api_file_lock_status_and_conflicts(tmp_path) -> None:
    app = create_app(tmp_path / "api.db")
    await call(endpoint(app, "/files/lock"), {"agent_id": "a1", "file": "frontend/index.html"})
    await call(endpoint(app, "/events"), {"event_type": "intent", "agent_id": "a2", "target": "frontend/index.html"})
    assert (await call(endpoint(app, "/files/{path:path}/status"), "frontend/index.html"))["locked"] is True
    assert (await call(endpoint(app, "/conflicts")))[0]["severity"] == "high"


def test_api_exposes_websocket_route(tmp_path) -> None:
    app = create_app(tmp_path / "api.db")
    paths = [getattr(route, "path", None) for route in app.routes]
    assert "/ws/agent/{agent_id}" in paths


def test_cli_register_and_join_isolated(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["register", "a1"])
    assert result.exit_code == 0
    result = runner.invoke(cli, ["join", "a1"])
    assert result.exit_code == 0
    assert "a1" in result.output


def test_cli_conflicts_command(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["lock", "a1", "--file", "frontend/index.html"])
    # The CLI has no raw intent command, so this verifies the command remains runnable.
    result = runner.invoke(cli, ["conflicts"])
    assert result.exit_code == 0
    assert "[" in result.output
