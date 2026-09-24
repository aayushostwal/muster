# Muster — Implementation Spec (v1)

Source of truth for the API contract, WebSocket protocol, process-manager
behavior, and CLI/install contract. Backend models already exist at
`backend/app/db/models.py` — do not change field names/types without updating
this file. PRD reference: see the "Muster — PRD" doc content summarized below.

## Repo layout

```
backend/        FastAPI app (native host process in prod; runs in a venv)
frontend/       Next.js App Router + TypeScript + Tailwind application
cli/            musterctl (bash script wrapping docker compose + service mgmt)
scripts/        install.sh, launchd plist template, systemd unit template
docker-compose.yml   Postgres + frontend only (backend runs natively)
```

## Data model

Implemented in `backend/app/db/models.py`:
`Project, DirectoryResource, DirectoryBinding, GlobalMcpServer, AgentProfile,
Skill, ProjectCapabilityOverride, Task, TaskInvocation, TaskEvent,
ToolApprovalRequest, Message, ContextSnapshot, CronJob, TaskRunAttempt, Secret`
plus legacy project-scoped
binding types retained for API compatibility.

Enums: `AgentBackend(claude_code, codex)`,
`TaskStatus(queued, running, waiting_on_you, done, failed, cancelled)`,
`MessageSender(user, agent, system)`, `AccessScope(read, read_write)`,
`FailureClass(transient, other)`.

## REST API (prefix `/api`)

All list endpoints return `{"items": [...]}`. All mutating endpoints return
the created/updated resource. 404 on missing id, 422 on validation error
(FastAPI default), 409 on conflicting unique constraint.

```
GET    /api/projects                       list
POST   /api/projects                       {name, description?, default_backend, default_model?, default_context_strategy?, primary_directory_id?}
GET    /api/projects/{id}
PATCH  /api/projects/{id}                  partial update
DELETE /api/projects/{id}

GET    /api/directories
POST   /api/directories                    {name, path, description?}
PATCH  /api/directories/{id}
DELETE /api/directories/{id}

GET    /api/mcp-servers
POST   /api/mcp-servers                    {name, description?, config, enabled?}
PATCH  /api/mcp-servers/{id}
DELETE /api/mcp-servers/{id}

GET    /api/agents
POST   /api/agents                         {name, backend, system_prompt, model?, thinking_level, config?, enabled?}
PATCH  /api/agents/{id}
DELETE /api/agents/{id}

GET    /api/skills
POST   /api/skills                         {name, description?, instructions, enabled?}
PATCH  /api/skills/{id}
DELETE /api/skills/{id}

GET    /api/global-tools
POST   /api/global-tools                   {name, description?, config, enabled?}
PATCH  /api/global-tools/{id}
DELETE /api/global-tools/{id}

GET    /api/projects/{id}/capabilities/{mcp|agent|skill|tool}
PUT    /api/projects/{id}/capabilities/{type}/{resource_id}  {enabled, config_override?}

GET    /api/models/{claude_code|codex}     one-hour cached local CLI catalog
                                                     ?refresh=true bypasses the cache

GET    /api/capability-imports/discover    read-only scan with redacted previews
POST   /api/capability-imports             {candidate_ids: [str]}
POST   /api/capability-imports/{id}/sync   explicitly re-sync one imported source

GET    /api/projects/{id}/directories
POST   /api/projects/{id}/directories      {directory_id, access_scope}
DELETE /api/projects/{id}/directories/{binding_id}

GET    /api/projects/{id}/mcp-servers
POST   /api/projects/{id}/mcp-servers      {name, config}   # stdio {command,args,env} or remote {transport,url,headers,bearer_token_env_var?}
PATCH  /api/projects/{id}/mcp-servers/{binding_id}
DELETE /api/projects/{id}/mcp-servers/{binding_id}

GET    /api/projects/{id}/tools
POST   /api/projects/{id}/tools            {name, config: {backend, decision, claude_pattern?, codex_prefix?}}
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
POST   /api/projects/{id}/tasks            {title, initial_prompt, backend?, model?, fallback_models?, tags?, thinking_level?, agent_id?, context_strategy?, media?}
                                            -> creates Task(status=queued), immediately calls
                                               process_manager.trigger(task) (fire-and-forget), 201

GET    /api/tasks                           ?status=<TaskStatus>&status=<TaskStatus>  # cross-project command center, newest activity first
GET    /api/tasks/{id}
POST   /api/tasks/{id}/cancel
POST   /api/tasks/{id}/restart
POST   /api/tasks/{id}/retry-now           # skip backoff wait, retry immediately
PATCH  /api/tasks/{id}/model               {model}       # switch model mid-conversation
PATCH  /api/tasks/{id}/models              {models}      # ordered primary/fallback model chain
PATCH  /api/tasks/{id}/thinking-level      {thinking_level}
PATCH  /api/tasks/{id}/context-strategy    {context_strategy}
PATCH  /api/tasks/{id}/tags                {tags}         # up to 8 workflow labels, 32 characters each
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
GET    /api/tasks/{id}/invocations         -> backend session ids and per-invocation token usage
GET    /api/tasks/{id}/events              -> structured tools, diffs, reasoning, logs, and sub-agent activity
GET    /api/tasks/{id}/tool-approvals      -> all pending/resolved runtime permission requests
POST   /api/tasks/{id}/tool-approvals/{approval_id}/resolve
                                            {decision: approve_once|always_allow|deny}
```

Capability discovery covers direct user resources plus active marketplace
plugin roots. Claude roots come from
`~/.claude/plugins/installed_plugins.json`; Codex roots come from enabled
`[plugins]` entries in `~/.codex/config.toml`. Unconfigured cache entries and
marketplace source repositories are ignored.

### WebSocket

```
WS /ws/tasks/{id}
```
Server -> client JSON events, one per line:
```json
{"type": "message", "message": {...Message...}}
{"type": "status", "status": "running"}
{"type": "run_attempt", "attempt": {...TaskRunAttempt...}}
{"type": "activity", "event": {...TaskEvent...}}
{"type": "invocation", "invocation": {...TaskInvocation...}}
{"type": "token_usage", "used": 12000, "limit": 200000}
{"type": "tool_approval", "approval": {...ToolApprovalRequest...}}
```
Client -> server: not used for sending chat (that's the REST POST, so it's
durable even if the socket drops); reserved for future typing indicators.

## Process manager (`backend/app/services/process_manager.py`)

Single in-process asyncio-based manager (module-level singleton), holding at
most one live subprocess per Task (`dict[task_id, RunningProcess]`).

`trigger(task_id)`:
1. If a process is already running for this task, just deliver the newest
   user message to its stdin (continued conversation) instead of spawning again.
2. Else: require the Project's read/write primary directory, mark Task
   `running`, resolve explicitly bound global directories and
   globally enabled MCP/agent/skill/tool resources with project overrides, load
   decrypted secrets, build the backend-specific command, spawn via
   `asyncio.create_subprocess_exec` with the primary directory as `cwd`, and
   start a reader task that:
   - parses each backend's streaming output into messages and structured
     `TaskEvent` rows, persists them, and broadcasts over the task's WebSocket;
   - stores the native Claude/Codex session id and token counters on the
     invocation record;
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
  for each bound directory, plus project `--allowedTools` / `--disallowedTools`
  patterns and `--mcp-config <tmp json file>` built from the
  Project's MCP bindings, plus `--model <model>` if set.
- Each stdout line is a JSON event (`stream-json`); map `type=="assistant"` to
  `AgentText`, `type=="result"` with `subtype=="success"` to `Done`, a
  captured `session_id` field to `SessionId` (stored on `Task.session_id`).
- Continued turns (same Task, new user message): re-invoke with
  `--resume <session_id> -p "<prompt>"` rather than keeping stdin open —
  Claude Code's headless mode is single-shot per invocation.
- Blocking question: if `stream-json` emits a `permission_denial` /
  tool-use request that requires approval (no `--permission-mode
  acceptEdits` coverage), persist a `ToolApprovalRequest`, stop the current
  turn, and surface inline allow-once / always-allow / deny actions. A
  resolution resumes the same native session with the chosen rule in force.

`codex.py` (`CodexAdapter`):
- Uses `codex exec "<prompt>" --json --sandbox workspace-write --cd <primary>`
  with repeated `--add-dir` flags for the first turn, and `codex exec resume
  <session_id> "<prompt>" --json` for continued turns. Project command-prefix
  permissions are rendered into a disposable `CODEX_HOME` rules overlay that
  links the user's auth, config, and sessions, so Muster never edits global
  Codex configuration.

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

## Frontend (`frontend/`, Next.js + TypeScript + Tailwind)

Routes: `/` (cross-project live operations command center), `/projects` (project
management), `/registry/:kind` (global directories, MCP connectors, agents, skills,
and tool policies), `/projects/:id` (project profile and
capability access), `/projects/:id/board` (task board), and `/tasks/:id`
(compact chat, activity timeline, multi-agent view, invocation telemetry,
model/thinking/context controls, and transcript).

`AppShell` also mounts a route-independent task composer. It resolves one
required `@project` mention, creates the task with that project's defaults,
and navigates to its live console. `Cmd/Ctrl+J` opens and focuses it.

API client: `frontend/lib/api.ts`, one typed function per endpoint above.
Runtime deployments set `window.__MUSTER_API_URL__`; build-time deployments
may set `NEXT_PUBLIC_API_URL`. The task stream is managed in
`frontend/hooks/use-task-stream.ts`.

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
