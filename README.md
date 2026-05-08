# Telepathy

Telepathy is a production-grade workspace intelligence layer for coding agents. It gives every agent a live radar view, persistent replay after reconnects, semantic intent broadcasts, zone-level activity, collaboration suggestions, anomaly detection, capacity tracking, deadlock detection, snapshots, health scoring, and mobile-friendly REST access.

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

## v2.0 REST API

```text
GET  /api/v2/snapshot
GET  /api/v2/agents/{agent_id}/replay
GET  /api/v2/zones
GET  /api/v2/intents
GET  /api/v2/suggestions
GET  /api/v2/anomalies
GET  /api/v2/capacity
GET  /api/v2/deadlocks
GET  /api/v2/integrations
GET  /api/v2/patterns
GET  /api/v2/health-score
POST /api/v2/snapshots
GET  /api/v2/snapshots
GET  /api/v2/snapshots/compare?left=...&right=...
```

## Architecture

- `telepathy/core`: SQLite storage and data models
- `telepathy/bus`: publish/subscribe event bus
- `telepathy/room`: shared workspace state and snapshots
- `telepathy/radar`: live views and conflict prediction
- `telepathy/stream`: WebSocket connection management
- `telepathy/subscriptions`: per-agent event filters
- `telepathy/v2`: workspace intelligence, replay, zones, suggestions, anomalies, capacity, snapshots, integrations, patterns, and health scoring
- `telepathy/server`: FastAPI app and WebSocket route
- `telepathy/cli.py`: Click CLI and demo
