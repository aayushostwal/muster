# Backend

FastAPI + SQLAlchemy (async) + Postgres service that owns Muster's entire
data model and is the only thing that actually spawns and talks to the
`claude` / `codex` CLIs. In production this process runs natively on the
host (launchd on macOS, systemd `--user` on Linux) rather than in a
container, specifically so it has unrestricted filesystem access to whatever
local directories a Project binds — no bind mounts, no redeploy to add a new
directory.

## What it owns

**Data model** (`app/db/models.py`) — SQLAlchemy tables covering the
full PRD: `Project` (with its directory/MCP/tool bindings, artifacts, cron
jobs and secrets), `Task` (the unit of agent work, with a status lifecycle
of `queued → running → waiting_on_you → done/failed/cancelled`), `Message`
(the persistent per-task chat, tagged by sender), `ContextSnapshot`
(compressed-history digests that sit alongside, never replacing, the raw
transcript), and `TaskRunAttempt` (the failure/retry audit trail a "Retry
now" button reads from). Schema changes are version-controlled through the
hand-written Alembic migrations in `alembic/versions/`.

**Capability import** (`app/services/capability_imports.py`) — read-only
discovery of user-level Claude Code and Codex agents, skills, and MCP servers.
Selected resources are copied into Muster's global registry with provenance
and a checksum, so a later scan can show whether a source changed and re-sync
it explicitly. Discovery previews expose key names and counts but never MCP
environment or header values. Native Claude/Codex files are never modified.

**REST + WebSocket API** (`app/api/routes/`) — one router per resource
(`projects`, `directories`, `mcp_servers`, `tools`, `artifacts`, `secrets`,
`cron`, `tasks`), plus `ws.py` which holds the only live connection to the
frontend: every Message, status change, and TaskRunAttempt the process
manager produces is pushed out through `ws.broadcast()`. Route handlers stay
thin — they persist rows and hand off to the services layer for anything
that involves a running process.

**Process manager** (`app/services/process_manager.py`) — an in-process
asyncio singleton that is the actual "control plane" in Muster's name. It
holds at most one live subprocess per Task, decides whether a new user
message should be piped into an already-running process or trigger a fresh
`--resume`'d invocation, and is the single place that flips a Task's status.
Creating a Task or posting a chat message are both fire-and-forget triggers
into this manager — there is deliberately no separate "run" action anywhere
in the API.

**Agent backend adapters** (`app/services/agent_backends/`) — thin,
swappable translation layers between the process manager's generic lifecycle
and each CLI's actual flags and streaming JSON format. `claude_code.py`
drives `claude -p ... --output-format stream-json --verbose` and resumes
conversations with `--resume <session_id>`; `codex.py` mirrors the same
shape against `codex exec`. Adding a third agent CLI means writing one more
adapter here, not touching the process manager.

**Failure handling** (`app/services/retry.py`) — classifies a failed run as
`transient` (usage/rate limits, network errors — auto-retried with
exponential backoff) or `other` (paused, waiting on the user), and every
attempt is written to both `TaskRunAttempt` and the chat as a system
message so the retry history is visible inline rather than hidden in logs.

**Context compression** (`app/services/context_compression.py`) — keeps the
most recent messages verbatim and asks the task's own agent backend to
summarize everything older into a `ContextSnapshot`, without ever deleting
the raw transcript on disk.

**Cron** (`app/services/cron_scheduler.py`) — an APScheduler instance kept
in sync with the `CronJob` table; each firing creates a Task exactly the way
a manual creation would, so scheduled work shows up on the same Kanban board.

**Secrets** (`app/core/security.py`) — Fernet symmetric encryption for
MCP-server API keys/tokens, keyed by a file on the host filesystem
(`~/.muster/secret.key`, mode 600) that never enters the database or git.

## Configuration

All runtime config is a single `pydantic-settings` model in `app/config.py`,
read from `MUSTER_`-prefixed environment variables (e.g.
`MUSTER_POSTGRES_HOST`) — there is no `DATABASE_URL` var; connection info is
always the individual `MUSTER_POSTGRES_*` fields, matching what
`scripts/install.sh` writes to `~/.muster/muster.env`.

## Running it

```bash
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8080
```

Tests (`tests/`) use an in-memory SQLite session in place of Postgres and
mock the process manager, so `pytest` needs no external services:

```bash
pytest
```
