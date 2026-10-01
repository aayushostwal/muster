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
Enabled Claude and Codex plugins are resolved through their installed-plugin
metadata, so marketplace capabilities such as Nexus are included without
scanning stale cache versions or uninstalled marketplace source checkouts.

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
Every invocation uses the Project's primary read/write directory as its
working directory and attaches its remaining directory grants. Project tool
rules are translated to native Claude allow/deny patterns or Codex exec-policy
rules; an uncovered permission request is persisted and pauses the Task until
the user allows it once, allows it for the Project, or denies it.
Creating a Task or posting a chat message are both fire-and-forget triggers
into this manager — there is deliberately no separate "run" action anywhere
in the API.

**MCP server** (`app/mcp_server.py`) — a local stdio adapter for Codex, Claude
Code, and other MCP clients. It exposes project discovery and the core Task
lifecycle as MCP tools, but deliberately calls the loopback REST API instead
of touching SQLAlchemy or the process manager directly. This preserves the
same validation, dispatch, permission, and PR-completion rules as the web UI.
The production entrypoint is the installed `muster-mcp` wrapper.

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

Agent runtime safeguards are configurable with
`MUSTER_RUNTIME_STARTUP_TIMEOUT_SECONDS` (default `60`),
`MUSTER_RUNTIME_IDLE_TIMEOUT_SECONDS` (default `1200`),
`MUSTER_RUNTIME_MAX_SECONDS` (default `7200`), and
`MUSTER_RUNTIME_STREAM_LIMIT_BYTES` (default `8388608`).

Native interactive task terminals are opt-in with
`MUSTER_INTERACTIVE_TERMINAL_ENABLED=true`. Set
`MUSTER_DEFAULT_TASK_RUNTIME_MODE=interactive` to make newly created manual
tasks use the Codex/Claude TUI. With terminal support enabled, new cron runs
also open the native CLI in the project's primary directory; otherwise they
use structured output. Existing tasks retain their saved runtime mode. The terminal
WebSocket is loopback-only and additionally checks
`MUSTER_TERMINAL_ALLOWED_ORIGINS`. PTY logs are stored beneath
`~/.muster/data/terminals` with owner-only permissions. Every fresh terminal
invocation has its own persisted native session ID. Codex history, state
databases, memories, and daemon control files are isolated beneath the task's
backend-session directory rather than linked from the user's global Codex home.
Enabled agent and skill instructions are injected lazily: a turn must invoke
`/resource-name`; unrelated global instruction bodies are not copied into every
prompt.

Send follow-ups through the composer beneath the task terminal, including
when its output is archived. A follow-up reopens the saved native Claude or
Codex conversation and retains its PR discussion. If no native session ID was
captured, Muster starts a new terminal with the original brief and persisted
messages. **Restart from beginning** still creates a new conversation.

## Running it

Recurring agents support a daily run window in **Recurring agents → Edit**.
For 11 AM–9 PM, enable **Limit to a daily run window**, set start `11:00`,
end `21:00`, and timezone `Asia/Kolkata`. Intervals start at the opening each
day; the closing time is exclusive. Overnight windows are supported. Without
a window, intervals keep their existing continuous cadence. Cron expressions
use the configured timezone; the window also filters their scheduled runs.
**Run now** bypasses the window and works for paused jobs. A run already in
progress at closing time is allowed to finish.

Recurring runs start unattended: Claude uses `--permission-mode auto` and
server-specific MCP allow rules (including imported native Claude connectors),
while Codex uses approval policy `never` within its workspace sandbox. These
settings also apply to **Run now** and resumed recurring tasks. Explicit deny
rules remain enforced. A denied tool ends a structured recurring run as failed
instead of leaving a pending approval. Connector authentication must already
be configured; auto mode does not sign in to Slack or Jira. Claude auto mode
requires a supported model (Sonnet 4.6+ or Opus 4.6+ on the Anthropic API;
Haiku is unsupported) and must be enabled by account/organization policy.
Claude `--permission-prompts none` requires CLI v2.1.259 or later. Existing
running terminals must be restarted to receive the new launch settings.

Each recurring agent keeps memory under
`~/.muster/data/recurring-agents/<agent-id>/` (or your configured data directory).
Muster refreshes `MEMORY.md` from the latest five run statuses and bounded agent
reports at launch and completion. The agent reads it alongside `NOTES.md`, which
it updates with verified mappings, processed message IDs, cursors, decisions and
open items. Notes survive new sessions, job edits and backend changes; each job
has its own directory. Memory is created on first invocation, including existing
jobs. Archived memory is retained when a job is deleted. Database source keys
and event receipts remain the authority for duplicate prevention. Reports are
unverified context, and agents are instructed to keep secrets and raw Slack
conversations out of their notes. The memory directory has owner-only access.

Recurring Claude runs also pre-approve literal MCP namespaces discovered from
installed user plugins, including `mcp__plugin_slack_slack__*`; project/local
plugin disable settings and explicit deny rules remain effective.

Recurring terminals close when their native CLI turn finishes. The final
summary and terminal output remain available for review; manual task terminals
are unaffected. Source tasks created through the Muster MCP tool must include
a stable `source_key` during recurring runs: `jira:<issue-id>` or
`slack:<channel-id>:<root-thread-timestamp>`. The same key in the same project
returns the existing task, including completed tasks, without launching it again.
For multiple Jira sites or Slack workspaces, include the site/workspace in the
key. Do not use a run timestamp, title, or changing issue status as the key.
Manual API task creation may omit it. Existing unkeyed tasks are not automatically
matched, and deleting a task releases its key. Apply migration
`0015_recurring_run_controls` before loading the updated backend.

```bash
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8080
```

With that API running, the MCP server can also be started directly during
development:

```bash
MUSTER_API_URL=http://127.0.0.1:8080 python -m app.mcp_server
```

Tests (`tests/`) use an in-memory SQLite session in place of Postgres and
mock the process manager, so `pytest` needs no external services:

```bash
pytest
```


Completed native terminal sessions open a scrollable session history showing
saved user prompts, agent replies, tool calls and results from the beginning.
History is paginated independently of the bounded PTY replay buffer; use
**Load more history** for subsequent entries and **View terminal output** to
switch back to the archived terminal. Existing task-local Codex conversations
and saved Claude session handles are supported. Missing native conversation
files are reported explicitly. Individual entries above 64K characters are
marked as abbreviated; internal instructions and hidden reasoning are excluded.

Recurring Claude memory permissions use `Read(path)` and `Edit(path)` rules.
Claude applies the Edit rule to all file-editing tools, including Write; a
`Write(path)` rule is not recognized by its file permission checks.
