"""PR delivery workflow: safe, structured "raise a PR" for a Task's working
tree (see docs/SPEC.md "PR delivery" and "Integration seams").

Design:
- Every external mutation is triggered by an explicit user action
  (`prepare` -> `confirm`, or `cancel` / `complete_without_pr`) -- nothing
  here runs automatically just because an agent turn ended.
  `process_manager` only calls `eligibility_hint()`, a read-only,
  side-effect-free check, to decide whether to broadcast a "Changes ready"
  suggestion; it never calls `prepare()`/`confirm()` itself.
- `confirm()` is gated the same way `ToolApprovalRequest` resolution is in
  `app/api/routes/tools.py`: the frontend renders an inline confirmation
  card (modeled on `ToolApprovalBar`) and only calls this after an explicit
  user decision. All git/`gh` mutation happens inside `confirm()`.
- All state lives in Postgres (`PrDeliveryRun`), so a backend restart
  mid-`confirm()` leaves the run in a non-terminal status that a follow-up
  read clearly reports as interrupted; a fresh `prepare()` call reuses that
  same row (idempotent) rather than creating a duplicate.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.ws import broadcast
from app.config import settings
from app.db.models import DirectoryResource, PrDeliveryRun, PrDeliveryStatus, PrPolicy, Project, Task

logger = logging.getLogger(__name__)

_PROTECTED_BRANCHES = {"main", "master", "trunk", "production", "release"}
_TERMINAL_STATUSES = {PrDeliveryStatus.succeeded, PrDeliveryStatus.failed, PrDeliveryStatus.rejected}
_GIT_STATUS_PREFIX_LEN = 3  # "XY " porcelain v1 prefix
_PR_NUMBER_RE = re.compile(r"/pull/(\d+)")
_SLUG_RE = re.compile(r"[^a-z0-9]+")

_locks: dict[uuid.UUID, asyncio.Lock] = {}


class PrDeliveryError(Exception):
    """A safety check failed or an external mutation returned an error.

    Carries a user-facing message; routes turn this into a 422.
    """


def _lock_for(task_id: uuid.UUID) -> asyncio.Lock:
    lock = _locks.get(task_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[task_id] = lock
    return lock


# -- subprocess plumbing -----------------------------------------------------


@dataclass
class _CommandResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


async def _run(cmd: list[str], cwd: str, timeout: float) -> _CommandResult:
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, OSError) as exc:
        return _CommandResult(127, "", str(exc))
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        await process.wait()
        return _CommandResult(124, "", f"timed out after {timeout}s: {' '.join(cmd)}")
    return _CommandResult(
        process.returncode or 0,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


def _parse_porcelain(output: str) -> list[str]:
    """Parse `git status --porcelain=v1` output into a sorted path list.

    Renames ("R  old -> new") collapse to the new path.
    """
    paths: set[str] = set()
    for line in output.splitlines():
        if not line or len(line) < _GIT_STATUS_PREFIX_LEN:
            continue
        rest = line[_GIT_STATUS_PREFIX_LEN:]
        if " -> " in rest:
            rest = rest.split(" -> ", 1)[1]
        cleaned = rest.strip().strip('"')
        if cleaned:
            paths.add(cleaned)
    return sorted(paths)


@dataclass
class GitContext:
    directory: str
    is_git_repo: bool
    has_remote: bool
    remote_url: str | None
    current_branch: str | None
    detached_head: bool
    dirty_paths: list[str]


async def capture_git_baseline(directory: str | None) -> list[str] | None:
    """Snapshot of dirty paths *before* a task's first invocation runs.

    Returns `None` (never an empty list standing in for "unknown") when the
    directory isn't a git repo or `git` itself failed, so callers can tell
    "captured, clean" apart from "capture failed / not a repo".
    """
    if not directory or not Path(directory).is_dir():
        return None
    repo_check = await _run(
        [settings.git_bin, "rev-parse", "--is-inside-work-tree"], directory, settings.pr_git_timeout_seconds
    )
    if not repo_check.ok or repo_check.stdout.strip() != "true":
        return None
    status = await _run(
        [settings.git_bin, "status", "--porcelain=v1"], directory, settings.pr_git_timeout_seconds
    )
    if not status.ok:
        return None
    return _parse_porcelain(status.stdout)


async def _inspect_repo(directory: str | None, remote_name: str) -> GitContext:
    if not directory or not Path(directory).is_dir():
        return GitContext(directory or "", False, False, None, None, False, [])
    repo_check = await _run(
        [settings.git_bin, "rev-parse", "--is-inside-work-tree"], directory, settings.pr_git_timeout_seconds
    )
    if not repo_check.ok or repo_check.stdout.strip() != "true":
        return GitContext(directory, False, False, None, None, False, [])

    branch = await _run(
        [settings.git_bin, "symbolic-ref", "--short", "-q", "HEAD"], directory, settings.pr_git_timeout_seconds
    )
    detached = not branch.ok
    current_branch = branch.stdout.strip() or None

    remote = await _run(
        [settings.git_bin, "remote", "get-url", remote_name], directory, settings.pr_git_timeout_seconds
    )
    has_remote = remote.ok and bool(remote.stdout.strip())

    status = await _run(
        [settings.git_bin, "status", "--porcelain=v1"], directory, settings.pr_git_timeout_seconds
    )
    dirty = _parse_porcelain(status.stdout) if status.ok else []

    return GitContext(
        directory=directory,
        is_git_repo=True,
        has_remote=has_remote,
        remote_url=remote.stdout.strip() or None,
        current_branch=current_branch,
        detached_head=detached,
        dirty_paths=dirty,
    )


async def _detect_default_branch(directory: str, remote_name: str) -> str | None:
    result = await _run(
        [settings.git_bin, "symbolic-ref", "--short", f"refs/remotes/{remote_name}/HEAD"],
        directory,
        settings.pr_git_timeout_seconds,
    )
    if result.ok and result.stdout.strip():
        return result.stdout.strip().rsplit("/", 1)[-1]
    return None


async def _ensure_branch(directory: str, head_branch: str) -> _CommandResult:
    exists = await _run(
        [settings.git_bin, "rev-parse", "--verify", "--quiet", head_branch],
        directory,
        settings.pr_git_timeout_seconds,
    )
    if exists.ok:
        return await _run([settings.git_bin, "checkout", head_branch], directory, settings.pr_git_timeout_seconds)
    return await _run(
        [settings.git_bin, "checkout", "-b", head_branch], directory, settings.pr_git_timeout_seconds
    )


def _is_protected(branch: str | None, base_override: str | None) -> bool:
    if branch is None:
        return False
    if base_override and branch == base_override:
        return True
    return branch.lower() in _PROTECTED_BRANCHES


def _diff_against_baseline(
    current_dirty: list[str], baseline_dirty: list[str], baseline_captured_at: datetime | None
) -> tuple[list[str], list[str]]:
    """Split `current_dirty` into (this task's paths, pre-existing/unrelated paths).

    An uncaptured baseline (task never ran, or capture failed) is *never*
    treated as "clean" -- everything is excluded so nothing ambiguous is
    silently swept into a PR.
    """
    if baseline_captured_at is None:
        return [], sorted(current_dirty)
    baseline_set = set(baseline_dirty)
    eligible = sorted(path for path in current_dirty if path not in baseline_set)
    excluded = sorted(path for path in current_dirty if path in baseline_set)
    return eligible, excluded


def suggest_branch_name(prefix: str, task: Task) -> str:
    slug = _SLUG_RE.sub("-", task.title.lower()).strip("-") or "task"
    short_id = str(task.id)[:8]
    clean_prefix = prefix.strip().strip("/")
    name = f"{clean_prefix}/{short_id}-{slug}" if clean_prefix else f"{short_id}-{slug}"
    return name[:120].rstrip("-")


def suggest_commit_message(task: Task, file_count: int) -> str:
    return f"{task.title.strip()}\n\n{file_count} file(s) changed by Muster task {str(task.id)[:8]}."


def suggest_pr_title(task: Task) -> str:
    return task.title.strip()[:300]


def suggest_pr_body(task: Task, file_paths: list[str]) -> str:
    file_list = "\n".join(f"- `{path}`" for path in file_paths[:50])
    more = f"\n- …and {len(file_paths) - 50} more" if len(file_paths) > 50 else ""
    prompt = task.initial_prompt.strip()[:2000]
    return (
        f"Delivered by Muster task `{task.id}`.\n\n"
        f"**Prompt**\n\n{prompt}\n\n"
        f"**Changed files ({len(file_paths)})**\n\n{file_list}{more}"
    )


def _assert_safe(ctx: GitContext, remote_name: str) -> None:
    if not ctx.is_git_repo:
        raise PrDeliveryError("The project working root is not a Git repository.")
    if not ctx.has_remote:
        raise PrDeliveryError(f"No '{remote_name}' remote is configured for this repository.")
    if ctx.detached_head:
        raise PrDeliveryError("Repository is in a detached HEAD state; check out a branch first.")


async def _resolve_directory(db: AsyncSession, project: Project) -> str | None:
    if project.primary_directory_id is None:
        return None
    directory = await db.get(DirectoryResource, project.primary_directory_id)
    return directory.path if directory else None


# -- provider abstraction (see docs/SPEC.md "PR delivery" #providers) -------


@dataclass
class ProviderPr:
    url: str
    number: int
    state: str


class Provider:
    """Extension point: implement this to support a PR host beyond GitHub."""

    name = "base"

    async def detect_repository(self, directory: str, remote_name: str) -> str | None:
        raise NotImplementedError

    async def find_existing_pr(
        self, directory: str, repository: str, head_branch: str
    ) -> ProviderPr | None:
        raise NotImplementedError

    async def create_pr(self, directory: str, run: PrDeliveryRun) -> ProviderPr:
        raise NotImplementedError

    async def get_pr_state(self, directory: str, run: PrDeliveryRun) -> tuple[str, bool]:
        """Returns (provider-reported state, reviewed)."""
        raise NotImplementedError


def _pr_number_from_url(url: str) -> int:
    match = _PR_NUMBER_RE.search(url)
    return int(match.group(1)) if match else 0


class GhCliProvider(Provider):
    """Local `gh` CLI path (the current repository standard)."""

    name = "github"

    async def detect_repository(self, directory: str, remote_name: str) -> str | None:
        result = await _run(
            [settings.gh_bin, "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            directory,
            settings.pr_provider_timeout_seconds,
        )
        return result.stdout.strip() or None if result.ok else None

    async def find_existing_pr(self, directory, repository, head_branch) -> ProviderPr | None:
        if not head_branch:
            return None
        result = await _run(
            [
                settings.gh_bin,
                "pr",
                "list",
                "--head",
                head_branch,
                "--state",
                "all",
                "--json",
                "url,number,state",
                "--limit",
                "1",
            ],
            directory,
            settings.pr_provider_timeout_seconds,
        )
        if not result.ok or not result.stdout.strip():
            return None
        try:
            items = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None
        if not items:
            return None
        item = items[0]
        return ProviderPr(url=item["url"], number=item["number"], state=str(item["state"]).lower())

    async def create_pr(self, directory, run: PrDeliveryRun) -> ProviderPr:
        args = [
            settings.gh_bin,
            "pr",
            "create",
            "--title",
            run.pr_title or "Muster changes",
            "--body",
            run.pr_body or "",
            "--base",
            run.base_branch or "main",
            "--head",
            run.head_branch or "",
        ]
        if run.draft:
            args.append("--draft")
        result = await _run(args, directory, settings.pr_provider_timeout_seconds)
        if not result.ok:
            detail = result.stderr.strip() or result.stdout.strip()
            raise PrDeliveryError(f"gh pr create failed: {detail[-1000:]}")
        lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
        url = lines[-1].strip() if lines else ""
        return ProviderPr(url=url, number=_pr_number_from_url(url), state="open")

    async def get_pr_state(self, directory, run: PrDeliveryRun) -> tuple[str, bool]:
        if not run.pr_number:
            return run.pr_state or "unknown", False
        result = await _run(
            [settings.gh_bin, "pr", "view", str(run.pr_number), "--json", "state,reviewDecision"],
            directory,
            settings.pr_provider_timeout_seconds,
        )
        if not result.ok:
            return run.pr_state or "unknown", False
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return run.pr_state or "unknown", False
        state = str(payload.get("state", run.pr_state or "unknown")).lower()
        reviewed = payload.get("reviewDecision") == "APPROVED" or state == "merged"
        return state, reviewed


_PROVIDERS: dict[str, Provider] = {"github": GhCliProvider()}


def _provider_for(name: str) -> Provider:
    provider = _PROVIDERS.get(name)
    if provider is None:
        raise PrDeliveryError(f"Unsupported PR provider: {name}")
    return provider


async def _detect_repository(provider_name: str, directory: str, remote_name: str) -> str | None:
    try:
        return await _provider_for(provider_name).detect_repository(directory, remote_name)
    except PrDeliveryError:
        return None


# -- serialization ------------------------------------------------------------


def _serialize(run: PrDeliveryRun) -> dict:
    return {
        "id": str(run.id),
        "task_id": str(run.task_id),
        "project_id": str(run.project_id),
        "status": run.status.value,
        "provider": run.provider,
        "repository": run.repository,
        "remote_name": run.remote_name,
        "head_branch": run.head_branch,
        "base_branch": run.base_branch,
        "draft": run.draft,
        "file_paths": run.file_paths,
        "excluded_paths": run.excluded_paths,
        "commit_message": run.commit_message,
        "pr_title": run.pr_title,
        "pr_body": run.pr_body,
        "validation_command": run.validation_command,
        "validation_output": run.validation_output,
        "pr_url": run.pr_url,
        "pr_number": run.pr_number,
        "pr_state": run.pr_state,
        "error_message": run.error_message,
        "completion_reason": run.completion_reason,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "resolved_at": run.resolved_at.isoformat() if run.resolved_at else None,
    }


# -- queries ------------------------------------------------------------------


async def get_active_run(db: AsyncSession, task_id: uuid.UUID) -> PrDeliveryRun | None:
    """The single in-flight (non-terminal) run for a task, if any."""
    result = await db.execute(
        select(PrDeliveryRun)
        .where(PrDeliveryRun.task_id == task_id, PrDeliveryRun.status.not_in(_TERMINAL_STATUSES))
        .order_by(PrDeliveryRun.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def latest_run(db: AsyncSession, task_id: uuid.UUID) -> PrDeliveryRun | None:
    result = await db.execute(
        select(PrDeliveryRun).where(PrDeliveryRun.task_id == task_id).order_by(PrDeliveryRun.created_at.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def list_runs(db: AsyncSession, task_id: uuid.UUID) -> list[PrDeliveryRun]:
    result = await db.execute(
        select(PrDeliveryRun).where(PrDeliveryRun.task_id == task_id).order_by(PrDeliveryRun.created_at)
    )
    return list(result.scalars().all())


async def eligibility(
    db: AsyncSession,
    task: Task,
    project: Project,
    *,
    base_branch: str | None = None,
    remote_name: str | None = None,
) -> dict:
    """Read-only, always-live snapshot of whether/why a PR can be raised now."""
    directory = await _resolve_directory(db, project)
    remote = remote_name or project.pr_remote_name
    ctx = await _inspect_repo(directory, remote)
    eligible_paths, excluded_paths = _diff_against_baseline(
        ctx.dirty_paths, task.git_baseline_dirty_paths, task.git_baseline_captured_at
    )
    base = base_branch or project.pr_base_branch
    is_protected = _is_protected(ctx.current_branch, base)

    ok = True
    reason: str | None = None
    if not directory:
        ok, reason = False, "This project has no primary directory configured."
    elif not ctx.is_git_repo:
        ok, reason = False, "The project working root is not a Git repository."
    elif not ctx.has_remote:
        ok, reason = False, f"No '{remote}' remote is configured for this repository."
    elif ctx.detached_head:
        ok, reason = False, "Repository is in a detached HEAD state."
    elif task.git_baseline_captured_at is None:
        ok, reason = False, "This task's change baseline was never captured; cannot safely scope a PR."
    elif not eligible_paths:
        ok, reason = False, "No eligible changes to deliver for this task."

    return {
        "policy": project.pr_policy,
        "is_git_repo": ctx.is_git_repo,
        "has_remote": ctx.has_remote,
        "remote_name": remote,
        "remote_url": ctx.remote_url,
        "current_branch": ctx.current_branch,
        "detached_head": ctx.detached_head,
        "is_protected_branch": is_protected,
        "baseline_captured": task.git_baseline_captured_at is not None,
        "dirty_paths": ctx.dirty_paths,
        "eligible_paths": eligible_paths,
        "excluded_paths": excluded_paths,
        "eligible": ok,
        "reason": reason,
    }


async def eligibility_hint(db: AsyncSession, task: Task, project: Project) -> dict | None:
    """Best-effort check used only to decide whether to surface "Changes
    ready -- Raise PR?" after an agent turn ends (see process_manager).
    Never raises; any failure just suppresses the suggestion.
    """
    if project.pr_policy == PrPolicy.manual:
        return None
    try:
        directory = await _resolve_directory(db, project)
        if not directory:
            return None
        ctx = await _inspect_repo(directory, project.pr_remote_name)
        if not ctx.is_git_repo or not ctx.has_remote or ctx.detached_head:
            return None
        eligible_paths, _ = _diff_against_baseline(
            ctx.dirty_paths, task.git_baseline_dirty_paths, task.git_baseline_captured_at
        )
        if not eligible_paths:
            return None
        return {"eligible_file_count": len(eligible_paths)}
    except Exception:  # noqa: BLE001 - never let this break turn completion
        logger.exception("pr_delivery.eligibility_hint failed for task %s", task.id)
        return None


# -- mutating workflow ---------------------------------------------------------


async def _refresh_prepared_run(
    db: AsyncSession,
    run: PrDeliveryRun,
    task: Task,
    project: Project,
    base_branch: str | None,
    remote_name: str | None,
    draft: bool | None,
) -> PrDeliveryRun:
    directory = await _resolve_directory(db, project)
    if not directory:
        raise PrDeliveryError("This project has no primary directory configured.")
    remote = remote_name or run.remote_name
    ctx = await _inspect_repo(directory, remote)
    _assert_safe(ctx, remote)
    eligible_paths, excluded_paths = _diff_against_baseline(
        ctx.dirty_paths, task.git_baseline_dirty_paths, task.git_baseline_captured_at
    )
    if not eligible_paths:
        raise PrDeliveryError("No eligible changes to deliver for this task.")

    run.remote_name = remote
    run.file_paths = eligible_paths
    run.excluded_paths = excluded_paths
    if base_branch:
        run.base_branch = base_branch
    if draft is not None:
        run.draft = draft
    run.commit_message = suggest_commit_message(task, len(eligible_paths))
    run.pr_body = suggest_pr_body(task, eligible_paths)
    await db.commit()
    await db.refresh(run)
    await broadcast(run.task_id, {"type": "pr_delivery", "run": _serialize(run)})
    return run


async def prepare(
    db: AsyncSession,
    task: Task,
    project: Project,
    *,
    base_branch: str | None = None,
    remote_name: str | None = None,
    draft: bool | None = None,
) -> PrDeliveryRun:
    """Compute eligibility and persist an `awaiting_confirmation` run.

    Never mutates the repository or calls a provider. Idempotent against
    rapid repeated clicks: reuses the task's existing `awaiting_confirmation`
    run instead of creating a second one; refuses to start a second run
    while one is already mid-flight (requirement: at most one active run).
    """
    async with _lock_for(task.id):
        # The asyncio lock covers one process; locking the durable Task row
        # also collapses rapid requests across multiple API workers.
        await db.execute(select(Task.id).where(Task.id == task.id).with_for_update())
        active = await get_active_run(db, task.id)
        if active is not None and active.status == PrDeliveryStatus.awaiting_confirmation:
            return await _refresh_prepared_run(db, active, task, project, base_branch, remote_name, draft)
        if active is not None:
            raise PrDeliveryError(
                f"A PR delivery run is already in progress ({active.status.value}) for this task."
            )

        directory = await _resolve_directory(db, project)
        if not directory:
            raise PrDeliveryError("This project has no primary directory configured.")
        remote = remote_name or project.pr_remote_name
        ctx = await _inspect_repo(directory, remote)
        _assert_safe(ctx, remote)

        eligible_paths, excluded_paths = _diff_against_baseline(
            ctx.dirty_paths, task.git_baseline_dirty_paths, task.git_baseline_captured_at
        )
        if not eligible_paths:
            if task.git_baseline_captured_at is None:
                raise PrDeliveryError(
                    "This task's change baseline was never captured; cannot safely scope a PR."
                )
            raise PrDeliveryError("No eligible changes to deliver for this task.")

        head_branch = suggest_branch_name(project.pr_branch_prefix, task)
        base = (
            base_branch
            or project.pr_base_branch
            or await _detect_default_branch(directory, remote)
            or ctx.current_branch
            or "main"
        )
        if head_branch.lower() in _PROTECTED_BRANCHES or head_branch == base:
            raise PrDeliveryError(f"Configured branch prefix produced an unsafe branch name: '{head_branch}'.")

        run = PrDeliveryRun(
            task_id=task.id,
            project_id=project.id,
            status=PrDeliveryStatus.awaiting_confirmation,
            provider=project.pr_provider,
            remote_name=remote,
            repository=await _detect_repository(project.pr_provider, directory, remote),
            head_branch=head_branch,
            base_branch=base,
            draft=draft if draft is not None else project.pr_draft_default,
            file_paths=eligible_paths,
            excluded_paths=excluded_paths,
            commit_message=suggest_commit_message(task, len(eligible_paths)),
            pr_title=suggest_pr_title(task),
            pr_body=suggest_pr_body(task, eligible_paths),
            validation_command=project.pr_validation_command,
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        await broadcast(run.task_id, {"type": "pr_delivery", "run": _serialize(run)})
        return run


async def _fail(db: AsyncSession, run: PrDeliveryRun, message: str) -> PrDeliveryRun:
    run.status = PrDeliveryStatus.failed
    run.error_message = message
    run.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(run)
    await broadcast(run.task_id, {"type": "pr_delivery", "run": _serialize(run)})
    return run


async def _progress(db: AsyncSession, run: PrDeliveryRun, status: PrDeliveryStatus) -> None:
    run.status = status
    await db.commit()
    await db.refresh(run)
    await broadcast(run.task_id, {"type": "pr_delivery", "run": _serialize(run)})


async def _finalize_success(db: AsyncSession, task: Task, run: PrDeliveryRun) -> None:
    await db.commit()
    await db.refresh(run)
    from app.services.task_tags import add_system_tag

    if await add_system_tag(db, task, "PR Raised"):
        await db.commit()
    await broadcast(run.task_id, {"type": "pr_delivery", "run": _serialize(run)})


async def confirm(
    db: AsyncSession,
    task: Task,
    project: Project,
    run: PrDeliveryRun,
    *,
    commit_message: str | None = None,
    pr_title: str | None = None,
    pr_body: str | None = None,
    draft: bool | None = None,
) -> PrDeliveryRun:
    """Perform the external mutation: validate, branch, commit, push, create/link PR.

    Idempotent: if `run` is already terminal (succeeded/failed/rejected),
    returns it unchanged instead of repeating any side effect -- this is
    what makes a double-click or a retry after a backend restart safe.
    """
    async with _lock_for(task.id):
        locked_run = (
            await db.execute(
                select(PrDeliveryRun).where(PrDeliveryRun.id == run.id).with_for_update()
            )
        ).scalar_one_or_none()
        if locked_run is None:
            raise PrDeliveryError("PR delivery run no longer exists.")
        run = locked_run
        if run.status != PrDeliveryStatus.awaiting_confirmation:
            return run

        directory = await _resolve_directory(db, project)
        if not directory:
            return await _fail(db, run, "Project working root is no longer configured.")

        ctx = await _inspect_repo(directory, run.remote_name)
        try:
            _assert_safe(ctx, run.remote_name)
        except PrDeliveryError as exc:
            return await _fail(db, run, str(exc))

        current_eligible, _ = _diff_against_baseline(
            ctx.dirty_paths, task.git_baseline_dirty_paths, task.git_baseline_captured_at
        )
        if not current_eligible:
            return await _fail(db, run, "No eligible changes remain to deliver.")
        if set(current_eligible) != set(run.file_paths):
            return await _fail(
                db, run, "The working tree changed since this PR was prepared. Re-run Prepare PR."
            )

        if commit_message:
            run.commit_message = commit_message
        if pr_title:
            run.pr_title = pr_title
        if pr_body:
            run.pr_body = pr_body
        if draft is not None:
            run.draft = draft

        provider = _provider_for(run.provider)

        await _progress(db, run, PrDeliveryStatus.validating)
        if run.validation_command:
            result = await _run(
                ["bash", "-lc", run.validation_command], directory, settings.pr_validation_timeout_seconds
            )
            run.validation_output = (result.stdout + "\n" + result.stderr)[-8000:]
            if not result.ok:
                return await _fail(db, run, f"Validation command failed (exit {result.returncode}).")

        existing = await provider.find_existing_pr(directory, run.repository or "", run.head_branch or "")
        if existing is not None:
            run.pr_url = existing.url
            run.pr_number = existing.number
            run.pr_state = existing.state
            run.status = PrDeliveryStatus.succeeded
            run.resolved_at = datetime.now(timezone.utc)
            await _finalize_success(db, task, run)
            return run

        await _progress(db, run, PrDeliveryStatus.pushing)

        checkout = await _ensure_branch(directory, run.head_branch or "")
        if not checkout.ok:
            return await _fail(
                db, run, f"Could not create branch '{run.head_branch}': {checkout.stderr.strip()[-500:]}"
            )

        add = await _run(
            [settings.git_bin, "add", "--", *run.file_paths], directory, settings.pr_git_timeout_seconds
        )
        if not add.ok:
            return await _fail(db, run, f"git add failed: {add.stderr.strip()[-500:]}")

        commit = await _run(
            [settings.git_bin, "commit", "-m", run.commit_message or suggest_commit_message(task, len(run.file_paths))],
            directory,
            settings.pr_git_timeout_seconds,
        )
        if not commit.ok and "nothing to commit" not in (commit.stdout + commit.stderr).lower():
            return await _fail(db, run, f"git commit failed: {commit.stderr.strip()[-500:]}")

        push = await _run(
            [settings.git_bin, "push", "--set-upstream", run.remote_name, run.head_branch or ""],
            directory,
            settings.pr_git_timeout_seconds,
        )
        if not push.ok:
            return await _fail(db, run, f"git push rejected: {push.stderr.strip()[-1000:]}")

        await _progress(db, run, PrDeliveryStatus.creating_pr)

        try:
            created = await provider.create_pr(directory, run)
        except PrDeliveryError as exc:
            return await _fail(db, run, str(exc))

        run.pr_url = created.url
        run.pr_number = created.number
        run.pr_state = created.state
        run.status = PrDeliveryStatus.succeeded
        run.resolved_at = datetime.now(timezone.utc)
        await _finalize_success(db, task, run)
        return run


async def cancel(db: AsyncSession, run: PrDeliveryRun) -> PrDeliveryRun:
    if run.status != PrDeliveryStatus.awaiting_confirmation:
        return run
    run.status = PrDeliveryStatus.rejected
    run.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(run)
    await broadcast(run.task_id, {"type": "pr_delivery", "run": _serialize(run)})
    return run


async def complete_without_pr(db: AsyncSession, task: Task, project: Project, reason: str) -> PrDeliveryRun:
    """Explicit "PR required" override, capturing why no PR was raised."""
    active = await get_active_run(db, task.id)
    if active is not None:
        active.status = PrDeliveryStatus.rejected
        active.completion_reason = reason
        active.resolved_at = datetime.now(timezone.utc)
        run = active
    else:
        run = PrDeliveryRun(
            task_id=task.id,
            project_id=project.id,
            status=PrDeliveryStatus.rejected,
            provider=project.pr_provider,
            remote_name=project.pr_remote_name,
            completion_reason=reason,
            resolved_at=datetime.now(timezone.utc),
        )
        db.add(run)
    await db.commit()
    await db.refresh(run)
    await broadcast(run.task_id, {"type": "pr_delivery", "run": _serialize(run)})
    return run


async def sync_status(db: AsyncSession, project: Project, run: PrDeliveryRun) -> PrDeliveryRun:
    """Poll the provider for the current PR state; the only path that may
    add the "PR Reviewed" tag (requirement: never from assistant prose).
    """
    if run.status != PrDeliveryStatus.succeeded or not run.pr_number:
        return run
    directory = await _resolve_directory(db, project)
    if not directory:
        return run
    provider = _provider_for(run.provider)
    state, reviewed = await provider.get_pr_state(directory, run)
    run.pr_state = state
    await db.commit()
    await db.refresh(run)
    if reviewed:
        task = await db.get(Task, run.task_id)
        if task is not None:
            from app.services.task_tags import add_system_tag

            if await add_system_tag(db, task, "PR Reviewed"):
                await db.commit()
    await broadcast(run.task_id, {"type": "pr_delivery", "run": _serialize(run)})
    return run


async def get_completion_gate(db: AsyncSession, task: Task, project: Project) -> dict:
    """Return the durable gate used by the explicit completion endpoint.

    A required project policy is satisfied by a provider-confirmed PR or by
    an explicit ``complete_without_pr`` override with a recorded reason. The
    gate never opens from assistant prose or a successful subprocess exit.
    """
    if project.pr_policy != PrPolicy.required:
        return {"satisfied": True, "reason": None}
    run = await latest_run(db, task.id)
    if run is None:
        return {"satisfied": False, "reason": "No PR has been raised for this task yet."}
    if run.status == PrDeliveryStatus.succeeded:
        return {"satisfied": True, "reason": None}
    if run.status == PrDeliveryStatus.rejected and run.completion_reason:
        return {"satisfied": True, "reason": run.completion_reason}
    return {"satisfied": False, "reason": "No PR has been confirmed for this task yet."}
