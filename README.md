# Muster

Muster is a self-hosted, local-first control plane for Claude Code and Codex
agent sessions. It runs Postgres and a web frontend in Docker while the
backend runs natively on your host (via a Python venv + `uvicorn`), giving
agent processes direct filesystem access to whatever project directories you
bind — no container bind mounts required. Projects, directory/MCP/tool
bindings, cron-scheduled tasks, and a Kanban-style task board are all
managed through a single web UI backed by one FastAPI service.

## Quick start

### Production-style install

```bash
curl -fsSL https://muster.dev/install.sh | bash
```

Installs Postgres + frontend containers, a backend venv, and a launchd/
systemd-supervised backend service. See [`docs/OPERATIONS.md`](docs/OPERATIONS.md)
for the full install/upgrade/uninstall flow and the `musterctl` command
reference.

### Local dev

```bash
# 1. Postgres + frontend in Docker
docker compose up -d postgres frontend

# 2. Backend, run directly (hot reload)
cd backend
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8080

# 3. Frontend dev server (separate terminal)
cd frontend
npm install
npm run dev
```

## Docs

- [`docs/SPEC.md`](docs/SPEC.md) — API/WebSocket contract, process manager
  design, agent backend adapters, CLI/install contract.
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — install/upgrade/uninstall
  flow, `musterctl` command reference, log locations.
