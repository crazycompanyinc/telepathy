# Telepathy

Telepathy is a real-time workspace awareness layer for coding agents. It gives every agent a live radar view of who is online, what files are locked, what changed recently, what CI or deploys are running, and where conflicts are likely.

## Quick Start

```bash
pip install -e ".[test]"
teleyt init
teleyt demo
```

Run the API and WebSocket server:

```bash
teleyt serve --port 8000
```

Then connect agents to:

```text
ws://localhost:8000/ws/agent/{agent_id}
```

## CLI

```bash
teleyt register <agent_id>
teleyt join <agent_id>
teleyt work <agent_id> --target frontend/index.html --task "Redesigning hero section"
teleyt lock <agent_id> --file frontend/index.html
teleyt radar
teleyt conflicts
teleyt serve --port 8000
```

## Architecture

- `telepathy/core`: SQLite storage and data models
- `telepathy/bus`: publish/subscribe event bus
- `telepathy/room`: shared workspace state and snapshots
- `telepathy/radar`: live views and conflict prediction
- `telepathy/stream`: WebSocket connection management
- `telepathy/subscriptions`: per-agent event filters
- `telepathy/server`: FastAPI app and WebSocket route
- `telepathy/cli.py`: Click CLI and demo
