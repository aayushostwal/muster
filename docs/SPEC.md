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
ToolApprovalRequest, PrDeliveryRun, Message, ContextSnapshot, CronJob,
TaskRunAttempt, Secret`
plus legacy project-scoped
binding types retained for API compatibility.

Enums: `AgentBackend(claude_code, codex)`,
`TaskStatus(queued, running, waiting_on_you, done, failed, cancelled)`,
`MessageSender(user, agent, system)`, `AccessScope(read, read_write)`,
`FailureClass(transient, other)`,
`PrPolicy(manual, preferred, required)` (Project-level PR delivery default),
`PrDeliveryStatus(awaiting_confirmation, validating, pushing, creating_pr,
succeeded, failed, rejected)`.

`Task` also carries `git_baseline_dirty_paths: list[str]` and
`git_baseline_captured_at: datetime | None` — a one-time snapshot of paths
already dirty before the task's first invocation, used to scope a PR to
*this task's* changes only (see "PR delivery" below).

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
POST   /api/tasks/{id}/restart             # stop any live invocation and start a new native
                                            # session from Task.initial_prompt; preserve history
POST   /api/tasks/{id}/retry-now           # skip backoff wait, retry immediately
PATCH  /api/tasks/{id}/backend             {backend}     # switch Claude Code/Codex using a fresh session + conversation handoff
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

GET    /api/tasks/{id}/pr-delivery/eligibility  -> live, side-effect-free snapshot of
                                            whether/why a PR can be raised right now
                                            (git repo?, remote?, detached HEAD?, files
                                            eligible vs. excluded, the task's current
                                            PrPolicy, and the active run if any)
GET    /api/tasks/{id}/pr-delivery         -> full history of PrDeliveryRun for this task
POST   /api/tasks/{id}/pr-delivery/prepare {base_branch?, remote_name?, draft?}
                                            -> computes eligibility and persists an
                                               `awaiting_confirmation` PrDeliveryRun;
                                               201. NEVER mutates the repository or calls
                                               a provider. Idempotent: re-preparing while
                                               a run is `awaiting_confirmation` refreshes
                                               that same run instead of creating another;
                                               422 while a run is mid-flight
                                               (validating/pushing/creating_pr) for this task.
POST   /api/tasks/{id}/pr-delivery/{run_id}/confirm
                                            {commit_message?, pr_title?, pr_body?, draft?}
                                            -> the ONLY endpoint that mutates the
                                               repository or calls a provider: runs the
                                               project's validation command (if
                                               configured), creates/checks out the
                                               feature branch, commits the exact file set
                                               shown at prepare() time, pushes, and
                                               creates (or links an existing) PR. A
                                               no-op returning the run unchanged if it is
                                               already terminal (double-click / retry-safe).
POST   /api/tasks/{id}/pr-delivery/{run_id}/cancel
                                            -> user declined the confirmation card;
                                               PrDeliveryStatus.rejected
POST   /api/tasks/{id}/pr-delivery/{run_id}/sync
                                            -> re-polls the provider for the PR's current
                                               state/review decision; the only path that
                                               may add the "PR Reviewed" tag
POST   /api/tasks/{id}/pr-delivery/complete-without-pr
                                            {reason}   -> explicit "PR required" override;
                                               see "PR delivery" below
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
{"type": "pr_delivery", "run": {...PrDeliveryRun...}}
{"type": "pr_suggestion", "eligible_file_count": 3}
```
`pr_suggestion` is a pure hint (no DB row backs it) broadcast once after a
turn concludes with eligible changes and `PrPolicy != manual` — see "PR
delivery" below. It is never itself a PrDeliveryRun.
Client -> server: not used for sending chat (that's the REST POST, so it's
durable even if the socket drops); reserved for future typing indicators.

### Interactive terminal WebSocket

Manual tasks may opt into `runtime_mode="interactive"`. These tasks run the
native Codex or Claude Code TUI inside a host POSIX PTY and use a separate,
bidirectional endpoint:

```
WS /ws/tasks/{id}/terminal
```

The first client frame must be
`{"type":"attach","cols":120,"rows":32,"after_seq":0}`. Subsequent client
frames are `input` (base64 bytes, maximum 64 KiB), `resize`, `take_control`,
and `ack`. Server frames are `ready`, `output` (base64 PTY bytes plus a
monotonic sequence), `gap`, `control`, `exit`, and `error`.

One attached browser owns the input lease; additional tabs are read-only
until they explicitly take control. Browser disconnects do not stop the PTY.
Output is retained in a bounded in-memory replay buffer and in a mode-0600 log
under `data/terminals/<task>/<invocation>.ttylog`. Cancel, restart, delete,
runtime switch, and backend shutdown terminate the entire PTY process group.

The terminal endpoint is disabled unless
`MUSTER_INTERACTIVE_TERMINAL_ENABLED=true`, accepts only loopback clients, and
checks the browser `Origin` against `MUSTER_TERMINAL_ALLOWED_ORIGINS`. It is
not a remotely exposed shell or a replacement for application authentication.
Cron tasks always use `runtime_mode="structured"` and the JSON process manager.
Existing tasks are migrated as structured tasks.

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
     invocation record, while `task_backend_sessions` keeps the durable
     resume handle and its Muster-owned storage path;
   - detects a blocking question (see below) and flips status to
     `waiting_on_you`;
   - on clean exit, flips status to `waiting_on_you` with
     `attention_reason="awaiting_review"`; a successful process/turn only
     proves that the runtime exited cleanly, not that the requested outcome
     was delivered;
   - on nonzero exit, classifies the failure (see Failure Handling) and
     either schedules a retry or flips to `failed` and waits.

Each subprocess starts in its own process group, stdout/stderr are drained
concurrently with an 8 MiB per-event stream limit, and a watchdog enforces
startup, idle, and total-runtime deadlines. Stopping a task terminates the
whole process group so shell and MCP children cannot become orphans. On API
startup, database rows left `running` by a prior crash are changed to
`waiting_on_you` and their open invocation is marked `interrupted`.

`switch_backend(task_id, backend)` stops any active invocation, supersedes
pending runtime-specific approvals, clears the native session id, selected
agent, and model chain, then starts the destination runtime in a fresh native
session. The first prompt contains the original brief and a bounded handoff of
the persisted conversation. Existing messages and invocation records remain
available for audit and are rendered with their original runtime labels.

### Task completion and resumption

`done` is an explicit conversation state, not a subprocess outcome. The user
sets it through `POST /api/tasks/{id}/complete` (the **Mark conversation
complete** action). `ProcessManager` serializes complete/cancel/restart/exit
transitions with a per-task lock; the first terminal action wins and repeated
clicks are idempotent. Posting another message to a completed, cancelled,
failed, or waiting task clears its terminal timestamps/attention reason and
resumes the native Claude/Codex session.

The UI presents `waiting_on_you` as two distinct stages using
`attention_reason`: `awaiting_review` is **Ready for review**, while
`blocking_question` and `tool_permission` are **Needs your input**. Sending a
follow-up optimistically shows **Reopening…**, then the persisted state moves
through `queued`/`running`. **Completed** is shown only for `done`; finishing a
single agent turn never makes the whole task appear complete.

Automatic completion is deliberately an extension point. It may be added only
for a trusted structured delivery event, such as a provider-confirmed PR or a
durably stored Canvas delivery record with explicit task provenance. A zero
exit code, a `Done` stream event, or assistant prose is never sufficient.

### Agent backends (`backend/app/services/agent_backends/`)

`base.py` defines `class AgentBackendAdapter(Protocol)` with:
```python
def build_command(self, task, project, bindings, secrets, prompt: str | None = None) -> BackendCommand: ...
def parse_line(self, raw: str) -> ParsedEvent | None: ...   # -> AgentText | BlockingQuestion | SessionId | Done | ErrorEvent
def resume_command(self, task, project, bindings, secrets, session_id: str) -> BackendCommand: ...
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
- Uses `codex exec - --json --sandbox workspace-write --cd <primary>` with
  the complete prompt written to stdin, repeated `--add-dir` flags for the
  first turn, and `codex exec resume <session_id> - --json` for continued
  turns. Project command-prefix
  permissions are rendered into a task-scoped `CODEX_HOME` under
  `MUSTER_DATA_DIR/backend-sessions`. The path is persisted in
  `task_backend_sessions` and reused on every turn; it links the user's auth,
  config, and sessions, so Muster never edits global Codex configuration.
  Older stale rollout paths are repaired to the matching file in the user's
  real Codex sessions directory before resume.
- PR create/update requests use a configured GitHub MCP connector and never
  start interactive `gh auth login` inside a headless task. Without that
  connector, the agent reports the missing project capability instead of
  initiating a device-authorization flow.

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

## PR delivery (`backend/app/services/pr_delivery.py`)

Safe, structured "raise a PR for this task's changes" workflow. Default
behavior is **PR preferred, not fully automatic**: a PR is only ever created
from an explicit user action (the "Prepare PR" quick action beside the task
composer, or the reserved `/pr` command — both resolve to the same
`prepare()` -> `confirm()` calls), never merely because an agent turn ended.

**State machine** (`PrDeliveryStatus`, persisted per-run in `pr_delivery_runs`):

```
awaiting_confirmation -> validating -> pushing -> creating_pr -> succeeded
                       \-> rejected                            \-> failed
```

- `prepare()` computes eligibility and creates/refreshes an
  `awaiting_confirmation` run. Never mutates the repository or calls a
  provider. Idempotent against rapid repeated clicks (reuses the task's
  existing `awaiting_confirmation` run rather than creating a duplicate; a
  second `prepare()` while a run is mid-flight returns 422).
- `confirm()` is the only function that mutates anything: runs the
  project's `pr_validation_command` (if configured), checks out/creates the
  feature branch, commits exactly the file set shown at `prepare()` time,
  pushes, and creates (or, if one already exists for the same
  repository/head branch, links) the PR. If `run` is already terminal
  (succeeded/failed/rejected) it is a no-op that returns the run unchanged —
  this is what makes a double-click, or a retry after a backend restart,
  safe. A per-task `asyncio.Lock` (mirroring `ProcessManager._lock_for`)
  serializes concurrent `confirm()` calls for the same task.

**Scoping to *this task's* changes** (never silently sweeping in unrelated
edits): `process_manager._spawn()` captures a one-time baseline of dirty
paths (`git status --porcelain`) the moment a task's first invocation
starts, stored on `Task.git_baseline_dirty_paths` /
`git_baseline_captured_at`. Eligibility is always `current dirty paths -
baseline dirty paths`; the pre-existing/overlapping paths are reported back
as `excluded_paths` so the confirmation card can show them, never silently
drop them. A task whose baseline was never captured (never ran, or capture
failed) is treated as **unknown**, not clean — nothing is eligible until a
real baseline exists.

**Safety checks**, all re-verified live (never cached) at both `prepare()`
and `confirm()` time: working root is a git repository; it has the
configured remote; HEAD is not detached; there is at least one eligible
file. `confirm()` additionally fails closed if the working tree changed
between `prepare()` and `confirm()` (the eligible file set no longer matches
exactly) rather than silently delivering a different diff than what the
user confirmed. The feature branch (name from `Project.pr_branch_prefix`,
per-task suffixed so it can never collide with `main`/`master`/`trunk`/etc.)
is always created/checked out before any push — `confirm()` never pushes to
whatever branch happened to be checked out.

**Confirmation card** (frontend, `pr-delivery-bar.tsx`) shows exactly what
`confirm()` is about to do before it runs: files, commit message, remote,
head branch, base branch, draft state, PR title, and body — editable, then
Confirm/Cancel. This mirrors the same "explicit user decision before an
external mutation" pattern as `ToolApprovalRequest` resolution
(`app/api/routes/tools.py`) without reusing that table directly (git
push/PR-create is a different domain from an in-turn tool-call approval).

**Provider abstraction** (`Provider` base class, `_PROVIDERS` registry):
today only `GhCliProvider` (the local `gh` CLI) is implemented, keyed by
`Project.pr_provider = "github"`. Adding another host means implementing
`detect_repository` / `find_existing_pr` / `create_pr` / `get_pr_state` and
registering it — nothing else in `pr_delivery.py` or the API routes is
GitHub-specific.

**Tags** (`Task.tags` assignments plus the persisted project catalog in
`project_task_tags`): `pr_delivery.py` is the only
code that ever adds `"PR Raised"` (on confirmed provider PR creation) or
`"PR Reviewed"` (only from `sync_status()` polling the provider's
`reviewDecision`/merge state). Structured Magic Canvas message media is the
only path that adds `"Canvas"`. These system tags are visible but read-only in
the tag manager and assignment controls; generic task APIs cannot manufacture
or remove them. Existing task JSON arrays remain valid and are lazily imported
into the project catalog, so the migration does not rewrite historical tasks.

**Project policy** (`PrPolicy` on `Project`): `manual` never broadcasts the
`pr_suggestion` hint; `preferred` (default) broadcasts it once a turn
concludes (`waiting_on_you`) with eligible changes; `required`
governs `get_completion_gate()` below. Policy never blocks the explicit
Prepare PR action/`/pr` — it only controls the passive suggestion.

**Integration with the task-completion lifecycle**: `get_completion_gate(db,
task, project) -> {"satisfied": bool, "reason": str | None}` is a pure,
side-effect-free read, wired into `POST /tasks/{id}/complete`
(`complete_task` in `app/api/routes/tasks.py`) — the explicit
"mark conversation complete" endpoint added by the task-completion
lifecycle work (`ProcessManager.complete()` in `process_manager.py`,
developed concurrently in this same working tree). When
`project.pr_policy == PrPolicy.required` and no PrDeliveryRun has
succeeded (or been explicitly overridden), `complete_task` returns 422
with the gate's reason instead of calling `process_manager.complete()`;
the user resolves this by raising and confirming a PR, or by calling
`POST /tasks/{id}/pr-delivery/complete-without-pr` (captures a reason,
satisfies the gate) first. `pr_delivery.py` and `process_manager.py`
otherwise stay decoupled — this is the only place their status logic
meets, and it lives at the route layer, not inside either service.

### Repeated “Raise a PR” instructions: product decision

| Option | Friction | Safety / fit |
| --- | --- | --- |
| Composer quick action | Low | Best default: visible at the decision point and opens confirmation without mutating git. |
| `/pr` slash command | Low for keyboard users | Useful alias for the same action; less discoverable by itself. |
| Reusable prompt template | Medium | Portable, but still ambiguous prose and cannot prove branch/diff/provider state. |
| Project completion policy | Low after setup | Appropriate only as `manual` / `preferred` / `required` gating; it must not create a PR automatically. |
| Automatic post-task workflow | Lowest apparent friction | Rejected as the default: a clean turn is not proof of delivery and automatic commit/push/PR creation has excessive blast radius. |

**Recommendation implemented:** the composer quick action, with `/pr` as a
keyboard alias, both call the same read-only `prepare()` path. A passive hint
appears only when the task has a captured baseline and a real eligible git
diff. Before any mutation the confirmation card rechecks the working tree,
shows the exact files, branch, remote, validation command, title/body, and
draft state, and requires explicit confirmation. The confirmed path still
requires a non-detached repository, configured remote, task-scoped changes,
a non-protected feature branch, successful optional validation, push access,
and authenticated provider permission. `required` policy may block explicit
completion, but its documented override captures a reason; it never silently
pushes or opens a PR.

## Integration seams (exact signatures — do not change without updating both sides)

`backend/app/services/process_manager.py` exports a module-level singleton:

```python
class ProcessManager:
    async def trigger(self, task_id: uuid.UUID) -> None: ...
    async def cancel(self, task_id: uuid.UUID) -> None: ...
    async def complete(self, task_id: uuid.UUID) -> None: ...
    async def retry_now(self, task_id: uuid.UUID) -> None: ...
    async def restart_from_beginning(self, task_id: uuid.UUID) -> None: ...
    async def switch_backend(self, task_id: uuid.UUID, backend: AgentBackend) -> None: ...

process_manager = ProcessManager()
```

Routes call `await process_manager.trigger(task.id)` after creating a Task
and after persisting a new user Message; the lifecycle methods back their
corresponding task actions, including runtime switching. All methods open
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

`backend/app/services/pr_delivery.py` exports (see "PR delivery" above):

```python
async def capture_git_baseline(directory: str | None) -> list[str] | None: ...
async def eligibility(db, task, project, *, base_branch=None, remote_name=None) -> dict: ...
async def eligibility_hint(db, task, project) -> dict | None: ...  # side-effect-free
async def prepare(db, task, project, *, base_branch=None, remote_name=None, draft=None) -> PrDeliveryRun: ...
async def confirm(db, task, project, run, *, commit_message=None, pr_title=None, pr_body=None, draft=None) -> PrDeliveryRun: ...
async def cancel(db, run) -> PrDeliveryRun: ...
async def complete_without_pr(db, task, project, reason: str) -> PrDeliveryRun: ...
async def sync_status(db, project, run) -> PrDeliveryRun: ...
async def get_completion_gate(db, task, project) -> dict: ...  # extension point, see above
class PrDeliveryError(Exception): ...  # routes turn this into HTTP 422
```

`process_manager._spawn()` calls `capture_git_baseline()` once per task
(best-effort, never raises into the spawn path) and `_on_process_exit()`
calls `_broadcast_pr_hint()` (which wraps `eligibility_hint()`) after
a turn concludes `waiting_on_you` — the only two places
`process_manager.py` touches PR delivery. Everything else (prepare/confirm/
cancel/sync/complete-without-pr) is invoked directly from
`app/api/routes/pr_delivery.py`, not from the process manager.

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

The task composer (`frontend/components/task/task-console.tsx`) carries a
"Prepare PR" quick action and the reserved `/pr` command (merged into the
same `/`-triggered menu as agents/skills in
`frontend/components/task/slash-command-menu.tsx`, distinguished by
`SlashCommandItem.kind === "action"`); both call the same
`PrDeliveryPanel` (`frontend/components/task/pr-delivery-bar.tsx`), which
renders the passive "Changes ready" suggestion, the pre-mutation
confirmation card, in-flight progress, and success/failure states inline
above the terminal. Project-level PR policy/branch/validation settings live
in the "Pull requests" tab of `frontend/components/project/resource-panels.tsx`.

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
