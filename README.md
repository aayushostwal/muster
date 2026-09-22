# Muster

Muster is a self-hosted, local-first control plane for Claude Code and Codex
agent sessions. It replaces a desktop full of terminal tabs with a single
web UI. Directories, MCP connectors, agents, and skills live in global
registries; projects receive explicit directory grants and can override the
globally available capabilities. Tasks are the unit of agent work, each with
its own persistent chat; creating a Task or sending it a message is the trigger —
there is no separate "run" button, no queue to babysit. Postgres and the
frontend run in Docker; the backend runs natively on your host so agent
processes get direct filesystem access to whatever you bind, with no
container mounts and no redeploy to add a new directory.

## Connect

<p align="center">
  <a href="https://www.linkedin.com/in/aayush-ostwal/"><img src="https://img.shields.io/badge/LinkedIn-0A66C2?style=flat&logo=linkedin&logoColor=white" style="margin: 0 4px"/></a>
  <a href="https://x.com/ostwal_aayush"><img src="https://img.shields.io/badge/X-000000?style=flat&logo=x&logoColor=white" style="margin: 0 4px"/></a>
  <a href="https://github.com/aayushostwal"><img src="https://img.shields.io/badge/GitHub-181717?style=flat&logo=github&logoColor=white" style="margin: 0 4px"/></a>
  <a href="https://medium.com/@aayushostwal"><img src="https://img.shields.io/badge/Medium-12100E?style=flat&logo=medium&logoColor=white" style="margin: 0 4px"/></a>
</p>

## Quick Start

### Production-style install

```bash
curl -fsSL https://muster.dev/install.sh | bash
```

Installs Postgres + frontend containers, a dedicated backend venv, and a
launchd (macOS) / systemd `--user` (Linux) supervised backend service. See
[`docs/OPERATIONS.md`](docs/OPERATIONS.md) for the full install / upgrade /
uninstall flow and the `musterctl` command reference.

### Local dev

```bash
# Install the pinned backend and frontend dependencies
make install

# Start Postgres and apply migrations
make db-up
make migrate

# Run these in separate terminals
make dev-backend
make dev-frontend  # http://localhost:5173
```

The Makefile uses `muster` as the local database password by default and
passes the same value to Docker Compose and the native backend. To use a
different password, export it once for the shell session before running the
commands above:

```bash
export DB_PASSWORD="your-local-password"
```

Run `make help` for the complete list of development, test, build, log, and
cleanup commands. To use the containerized frontend on port 3000 instead of
Vite, run `make up` rather than `make db-up`.

## What Muster Does

- Create a Task with a prompt, and the configured agent (Claude Code or
  Codex) starts on it immediately — no manual "run" step, ever.
- Keep chatting with a Task the same way you'd chat with anything else;
  sending a message is what wakes the agent back up, whether it's idle,
  mid-run, or waiting on you.
- Get blocked mid-run — a permission prompt or a clarifying question lands
  directly in the Task's chat and flips its status to *Waiting on You*.
  There's no separate notification channel to check.
- Manage directories, MCP connectors, agents, and skills once in global
  registries. Projects explicitly bind directories and can enable or disable
  every other capability without duplicating configuration.
- Inspect every invocation's native Claude/Codex session id, API token usage,
  tool calls, diffs, reasoning, runtime logs, and delegated-agent activity.
- Select an ordered model chain from the live local CLI catalog, tune thinking
  effort, and switch context strategy without losing conversation history.
- Schedule recurring agent runs with Cron Jobs — they land on the same
  Kanban board as anything triggered by hand.
- Trust that a transient failure (a usage limit, a network blip) retries
  itself with backoff, logged inline in the chat, while anything else pauses
  cleanly for you instead of guessing.
- Restart the whole stack and pick up exactly where you left off — in-flight
  Task state, chat history, and schedules all recover without
  reconfiguration.

## Modules

| Module | Purpose | Docs |
| --- | --- | --- |
| `backend/` | FastAPI + async SQLAlchemy + Postgres service. Owns the data model, the REST/WebSocket API, the process manager that spawns and streams the `claude`/`codex` CLIs, failure classification and retry, context compression, and the cron scheduler. | [`backend/README.md`](backend/README.md) |
| `frontend/` | Next.js App Router + TypeScript + Tailwind command center. Global registries → Project access controls → Kanban task board → compact live execution console, driven by TanStack Query and per-task WebSockets. | [`frontend/README.md`](frontend/README.md) |
| `cli/` | `musterctl` — the single command covering install, start/stop/restart, status, logs, upgrade, uninstall, database backup/restore, config, and a `doctor` healthcheck, across both launchd and systemd. | [`cli/README.md`](cli/README.md) |
| `scripts/` | `install.sh` and the launchd/systemd service templates it substitutes at install time — the one-shot path from a bare machine to a running Muster instance. | [`scripts/README.md`](scripts/README.md) |
| `docs/` | `SPEC.md` (the API/WebSocket contract, process-manager design, and agent-backend adapter behavior that every module above is implemented against) and `OPERATIONS.md` (the full `musterctl` reference and install/upgrade/uninstall flow). | [`docs/SPEC.md`](docs/SPEC.md) · [`docs/OPERATIONS.md`](docs/OPERATIONS.md) |

## Core Concepts

| Entity | What it is |
| --- | --- |
| **Project** | A workspace with explicit directory grants, per-capability overrides, artifacts, schedules, secrets, and default runtime settings. |
| **Global capability** | A reusable directory, MCP connector, agent profile, or skill. MCP/agent/skill resources are available to projects by default; directories require an explicit grant. |
| **Task** | The unit of agent work inside a Project — prompt, runtime, ordered model chain, thinking level, context strategy, and its own Chat. |
| **Chat** | The ordered Messages tied to a Task — user, agent, and system senders, with a blocking-question flag for the human-in-the-loop flow. |
| **Invocation** | One Claude or Codex process run, including native session id, selected model, status, and input/output/cache token counts. |
| **Task event** | A structured, collapsible tool call, diff, reasoning block, runtime log, or delegated-agent event. |
| **Artifact** | A named binding inside a Project, e.g. a GitHub repo tied to a local path and optionally a remote service URL. |
| **Directory binding** | A project-scoped read or read-write grant to a globally registered filesystem root. |
| **Cron Job** | A scheduled Task template: a cron expression plus the prompt/backend/model to run, still surfaced on the same Task board. |
| **Context Snapshot** | A compressed summary of a Task's chat history, stored alongside — never in place of — the full raw transcript. |

Task status moves through a fixed lifecycle: **Queued → Running → Waiting on
You → Done / Failed / Cancelled**, with every retry attempt and backoff
interval logged inline as a system message.

## Tech Stack

| Layer | Choice |
| --- | --- |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Alembic, APScheduler |
| Database | PostgreSQL 16 — chosen for safe concurrent writes across simultaneous Task runs |
| Frontend | Next.js App Router, React, TypeScript, Tailwind CSS, Framer Motion, TanStack Query |
| Agent backends | `claude` (Claude Code CLI, headless `stream-json` mode) and `codex` (Codex CLI, `exec --json` mode) |
| Deployment | Docker Compose for Postgres + frontend; the backend runs natively on the host as a launchd agent (macOS) or systemd `--user` unit (Linux) |

## Development

```bash
# Backend tests (in-memory SQLite, no external services required)
cd backend && pip install -r requirements.txt && pytest

# Frontend type-check
cd frontend && npm install && npx tsc --noEmit
```

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for
the full text.

## SEO / GEO Tags

`claude code`, `codex cli`, `ai agent orchestrator`, `self-hosted ai agents`,
`local ai control plane`, `claude code control plane`, `agent task manager`,
`cron scheduled ai agents`, `ai coding agent dashboard`, `mcp server manager`,
`human in the loop ai agents`, `postgres task queue`, `fastapi agent backend`,
`react kanban board`, `launchd systemd service`, `ai agent chat ui`,
`developer productivity`, `local first software`
