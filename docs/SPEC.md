# Muster — Implementation Spec (v1)

Source of truth for the API contract, WebSocket protocol, process-manager
behavior, and CLI/install contract. Backend models already exist at
`backend/app/db/models.py` — do not change field names/types without updating
this file. PRD reference: see the "Muster — PRD" doc content summarized below.

## Repo layout

```
backend/        FastAPI app (native host process in prod; runs in a venv)
frontend/       React + Vite + TS SPA
cli/            musterctl (bash script wrapping docker compose + service mgmt)
scripts/        install.sh, launchd plist template, systemd unit template
docker-compose.yml   Postgres + frontend only (backend runs natively)
```

## Data model

Already implemented in `backend/app/db/models.py`:
`Project, DirectoryBinding, McpBinding, ToolBinding, ProjectArtifact, Task,
Message, ContextSnapshot, CronJob, TaskRunAttempt, Secret`.

Enums: `AgentBackend(claude_code, codex)`,
`TaskStatus(queued, running, waiting_on_you, done, failed, cancelled)`,
`MessageSender(user, agent, system)`, `AccessScope(read, read_write)`,
`FailureClass(transient, other)`.

## REST API (prefix `/api`)

All list endpoints return `{"items": [...]}`. All mutating endpoints return
the created/updated resource. 404 on missing id, 422 on validation error
(FastAPI default), 409 on conflicting unique constraint.

```
GET    /api/projects                       list (excl. archived unless ?archived=true)
POST   /api/projects                       {name, description?, default_backend, default_model?, default_context_strategy?}
GET    /api/projects/{id}
PATCH  /api/projects/{id}                  partial update
POST   /api/projects/{id}/archive
POST   /api/projects/{id}/unarchive

GET    /api/projects/{id}/directories
POST   /api/projects/{id}/directories      {path, access_scope}
DELETE /api/projects/{id}/directories/{binding_id}

GET    /api/projects/{id}/mcp-servers
POST   /api/projects/{id}/mcp-servers      {name, config}   # config validated against a minimal schema: {command: str, args: [str], env: {str:str}}
PATCH  /api/projects/{id}/mcp-servers/{binding_id}
DELETE /api/projects/{id}/mcp-servers/{binding_id}

GET    /api/projects/{id}/tools
POST   /api/projects/{id}/tools            {name, config}
DELETE /api/projects/{id}/tools/{binding_id}

GET    /api/projects/{id}/artifacts
POST   /api/projects/{id}/artifacts        {name, local_path, remote_url?}
DELETE /api/projects/{id}/artifacts/{artifact_id}

GET    /api/projects/{id}/secrets                  # names only, never values
PUT    /api/projects/{id}/secrets/{key_name}       {value}   # upsert, encrypts at rest
DELETE /api/projects/{id}/secrets/{key_name}

GET    /api/projects/{id}/cron-jobs
POST   /api/projects/{id}/cron-jobs        {name, schedule_expr, prompt, backend, model?}
PATCH  /api/projects/{id}/cron-jobs/{cron_id}
POST   /api/projects/{id}/cron-jobs/{cron_id}/enable
POST   /api/projects/{id}/cron-jobs/{cron_id}/disable
DELETE /api/projects/{id}/cron-jobs/{cron_id}

GET    /api/projects/{id}/tasks            ?status=<TaskStatus>  # for the Kanban board
POST   /api/projects/{id}/tasks            {title, initial_prompt, backend?, model?, context_strategy?, media?}
                                            -> creates Task(status=queued), immediately calls
                                               process_manager.trigger(task) (fire-and-forget), 201

GET    /api/tasks/{id}
POST   /api/tasks/{id}/cancel
POST   /api/tasks/{id}/restart
POST   /api/tasks/{id}/retry-now           # skip backoff wait, retry immediately
PATCH  /api/tasks/{id}/model               {model}       # switch model mid-conversation
PATCH  /api/tasks/{id}/context-strategy    {context_strategy}
POST   /api/tasks/{id}/compress-context    -> creates ContextSnapshot, summarizing all Messages
                                               older than the most recent N turns via the task's
                                               own backend in a one-shot summarization call

GET    /api/tasks/{id}/messages
POST   /api/tasks/{id}/messages            {content_text?, media?}
                                            -> persists a user Message, flips status if needed,
                                               and calls process_manager.trigger(task) — this is
                                               the ONLY send path; there is no separate "run" action
GET    /api/tasks/{id}/transcript          -> raw transcript text (full, uncompressed) from disk

GET    /api/tasks/{id}/run-attempts        -> failure/retry log for the "Retry now" UI
```

### WebSocket

```
WS /ws/tasks/{id}
```
Server -> client JSON events, one per line:
```json
{"type": "message", "message": {...Message...}}
{"type": "status", "status": "running"}
{"type": "run_attempt", "attempt": {...TaskRunAttempt...}}
{"type": "token_usage", "used": 12000, "limit": 200000}
```
Client -> server: not used for sending chat (that's the REST POST, so it's
durable even if the socket drops); reserved for future typing indicators.

## Process manager (`backend/app/services/process_manager.py`)

Single in-process asyncio-based manager (module-level singleton), holding at
most one live subprocess per Task (`dict[task_id, RunningProcess]`).

`trigger(task_id)`:
1. If a process is already running for this task, just deliver the newest
   user message to its stdin (continued conversation) instead of spawning again.
2. Else: mark Task `running`, load Project's directory/MCP/tool bindings +
   decrypted secrets, build the backend-specific command, spawn via
   `asyncio.create_subprocess_exec`, and start a reader task that:
   - parses each backend's streaming output into `Message(sender=agent)` rows,
     persists them, and broadcasts over the task's WebSocket;
   - detects a blocking question (see below) and flips status to
     `waiting_on_you`;
   - on clean exit, flips status to `done`;
   - on nonzero exit, classifies the failure (see Failure Handling) and
     either schedules a retry or flips to `failed` and waits.

### Agent backends (`backend/app/services/agent_backends/`)

`base.py` defines `class AgentBackendAdapter(Protocol)` with:
```python
def build_command(self, task, project, bindings, secrets) -> list[str]: ...
def parse_line(self, raw: str) -> ParsedEvent | None: ...   # -> AgentText | BlockingQuestion | SessionId | Done | ErrorEvent
def resume_command(self, task, project, bindings, secrets, session_id: str) -> list[str]: ...
```

`claude_code.py` (`ClaudeCodeAdapter`):
- First turn: `claude -p "<prompt>" --output-format stream-json --permission-mode acceptEdits --add-dir <dir> ...`
  for each bound directory, plus `--mcp-config <tmp json file>` built from the
  Project's MCP bindings, plus `--model <model>` if set.
- Each stdout line is a JSON event (`stream-json`); map `type=="assistant"` to
  `AgentText`, `type=="result"` with `subtype=="success"` to `Done`, a
  captured `session_id` field to `SessionId` (stored on `Task.session_id`).
- Continued turns (same Task, new user message): re-invoke with
  `--resume <session_id> -p "<prompt>"` rather than keeping stdin open —
  Claude Code's headless mode is single-shot per invocation.
- Blocking question: if `stream-json` emits a `permission_denial` /
  tool-use request that requires approval (no `--permission-mode
  acceptEdits` coverage), treat that event as `BlockingQuestion` with the
  raw text; the user's next message is delivered via a resumed invocation
  that includes their answer as the prompt.

`codex.py` (`CodexAdapter`):
- Uses `codex exec "<prompt>" --json` for the first turn (Codex CLI's
  non-interactive mode), and `codex exec resume <session_id> "<prompt>" --json`
  for continued turns, mirroring the same event mapping.

Both adapters are intentionally thin translation layers — if the installed
CLI's actual flags differ from the above by version, `musterctl doctor`
should surface a clear "backend CLI not found / --help mismatch" error rather
than the process manager failing silently.

### Failure handling & retry (`backend/app/services/retry.py`)

`classify(exit_code, stderr_tail) -> FailureClass`:
- `transient` if stderr matches known patterns: rate/usage limit
  (`usage limit`, `rate limit`, `429`), network (`ECONNRESET`, `timeout`,
  `getaddrinfo`, `network`).
- else `other`.

On `transient`: create a `TaskRunAttempt` row (+ mirrored system `Message`),
compute backoff `min(retry_base_seconds * 2**attempt, retry_max_seconds)`,
schedule a retry via `asyncio.create_task(asyncio.sleep(backoff); trigger(...))`,
keep Task status `running` (surfaced in the UI as "retrying in Ns" from the
latest `TaskRunAttempt`). Stop after `retry_max_attempts` and fall through to
`other` handling.

On `other`: create `TaskRunAttempt` (+ system Message), set Task `failed`,
stop. The `/retry-now` endpoint re-invokes `trigger()` immediately,
bypassing the backoff sleep.

### Context compression (`backend/app/services/context_compression.py`)

`compress(task_id)`: takes all `Message` rows for the task, keeps the most
recent 10 verbatim, summarizes everything older via a one-shot call to the
task's own backend adapter (`claude -p "Summarize this conversation: ..."`),
writes a `ContextSnapshot` (summary_text + a copy of the full raw transcript
path already on disk), and future `trigger()` calls prepend the latest
snapshot's summary instead of full history once one exists. The raw
transcript file is never deleted — the UI's "expand full transcript" reads
it directly.

## Integration seams (exact signatures — do not change without updating both sides)

`backend/app/services/process_manager.py` exports a module-level singleton:

```python
class ProcessManager:
    async def trigger(self, task_id: uuid.UUID) -> None: ...
    async def cancel(self, task_id: uuid.UUID) -> None: ...
    async def retry_now(self, task_id: uuid.UUID) -> None: ...

process_manager = ProcessManager()
```

Routes call `await process_manager.trigger(task.id)` after creating a Task
and after persisting a new user Message; `cancel`/`retry_now` back
`/api/tasks/{id}/cancel` and `/api/tasks/{id}/retry-now`. All three open
their own DB session internally (they don't take one as an argument) so
routes never need to pass session state across the fire-and-forget boundary.

`backend/app/api/routes/ws.py` exports:

```python
async def broadcast(task_id: uuid.UUID, event: dict) -> None: ...
```

`process_manager` imports and calls `broadcast()` after persisting each
Message / status change / TaskRunAttempt — it is the only writer to
WebSocket clients. `ws.py` itself just accepts connections, registers them
in a `dict[uuid.UUID, set[WebSocket]]`, and forwards whatever `broadcast()`
is given.

`backend/app/services/cron_scheduler.py` exports:

```python
scheduler = AsyncIOScheduler(...)  # started/stopped from main.py's lifespan
def sync_jobs_from_db() -> None: ...  # called on startup and after any CronJob CRUD
```

CronJob CRUD routes call `sync_jobs_from_db()` after create/update/enable/
disable/delete so the in-memory APScheduler stays in sync with Postgres.
Each scheduled firing creates a Task (backend=cron_job.backend,
initial_prompt=cron_job.prompt, cron_job_id=cron_job.id) and calls
`process_manager.trigger()`, exactly like the manual creation path.

## Frontend (`frontend/`, React + Vite + TS)

Routes: `/` (Projects list) → `/projects/:id` (tabs: Directories, MCP/Tools,
Artifacts, Cron, Secrets) → `/projects/:id/board` (Kanban by TaskStatus) →
`/tasks/:id` (chat + model/context controls + token usage + transcript
toggle + Retry-now banner when applicable).

API client: `frontend/src/api/client.ts`, one typed function per endpoint
above, base URL from `import.meta.env.VITE_API_URL` (default
`http://localhost:8080`). WebSocket client in `frontend/src/api/ws.ts`.

State: React Query for server state, no global state library needed.

## CLI / install contract

See `docs/OPERATIONS.md` for the full `musterctl` command table and
install/upgrade/uninstall flow — implemented by `scripts/install.sh`,
`scripts/launchd/*.plist.template`, `scripts/systemd/*.service.template`,
and `cli/musterctl`.

Pragmatic simplification vs. the PRD's "single compiled binary": the backend
is Python/FastAPI, so the "native service" is `uvicorn` running inside a
dedicated venv at `~/.muster/venv`, supervised by launchd/systemd — not a
cross-compiled Go/Rust binary. `musterctl` itself is a POSIX shell script
installed to `/usr/local/bin/musterctl` (or `~/.local/bin` if unwritable).
This keeps install correctness high without a cross-platform binary release
pipeline; documented explicitly, not silently substituted.
