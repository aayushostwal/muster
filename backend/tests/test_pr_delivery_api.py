"""Coverage for the PR delivery workflow: state transitions, idempotency,
safety rejection paths, and duplicate PR prevention.

All `git`/`gh` subprocess calls are faked via a scripted `FakeGit` dispatcher
monkeypatched over `pr_delivery._run`, so these tests are deterministic and
do not depend on `git`/`gh` binaries or network access.
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.routes import pr_delivery as pr_delivery_routes
from app.api.routes import projects as projects_routes
from app.api.routes import tasks as tasks_routes
from app.config import settings
from app.db.models import AgentBackend, DirectoryResource, PrDeliveryStatus, Project, Task
from app.db.session import get_db
from app.services import pr_delivery
from app.services.pr_delivery import PrDeliveryError, _CommandResult


class FakeGit:
    """Scripted stand-in for `pr_delivery._run`, dispatching by argv."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.dirty_paths: list[str] = []
        self.remote_url: str | None = "git@github.com:acme/widgets.git"
        self.current_branch: str | None = "feature/x"
        self.default_branch = "main"
        self.existing_local_branches: set[str] = set()
        self.push_ok = True
        self.gh_repo = "acme/widgets"
        self.existing_pr: dict | None = None
        self.create_pr_url = "https://github.com/acme/widgets/pull/42"
        self.validation_ok = True
        self.is_repo = True
        self.detached = False

    async def __call__(self, cmd: list[str], cwd: str, timeout: float) -> _CommandResult:
        self.calls.append(cmd)
        exe = cmd[0]
        if exe == settings.git_bin:
            sub = cmd[1]
            if sub == "rev-parse" and "--is-inside-work-tree" in cmd:
                return _CommandResult(0 if self.is_repo else 128, "true\n" if self.is_repo else "", "")
            if sub == "rev-parse":
                branch = cmd[-1]
                exists = branch in self.existing_local_branches
                return _CommandResult(0 if exists else 1, "", "")
            if sub == "symbolic-ref" and cmd[-1] == "HEAD":
                if self.detached or self.current_branch is None:
                    return _CommandResult(1, "", "not a symbolic ref")
                return _CommandResult(0, f"{self.current_branch}\n", "")
            if sub == "symbolic-ref":
                return _CommandResult(0, f"refs/remotes/origin/{self.default_branch}\n", "")
            if sub == "remote":
                if self.remote_url:
                    return _CommandResult(0, f"{self.remote_url}\n", "")
                return _CommandResult(1, "", "no such remote")
            if sub == "status":
                lines = "".join(f" M {p}\n" for p in self.dirty_paths)
                return _CommandResult(0, lines, "")
            if sub in {"checkout", "add", "commit"}:
                return _CommandResult(0, "", "")
            if sub == "push":
                return _CommandResult(0 if self.push_ok else 1, "", "" if self.push_ok else "! [rejected]")
        if exe == settings.gh_bin:
            if cmd[1:3] == ["repo", "view"]:
                return _CommandResult(0, f"{self.gh_repo}\n", "")
            if cmd[1:3] == ["pr", "list"]:
                payload = [self.existing_pr] if self.existing_pr else []
                return _CommandResult(0, json.dumps(payload), "")
            if cmd[1:3] == ["pr", "create"]:
                return _CommandResult(0, f"{self.create_pr_url}\n", "")
            if cmd[1:3] == ["pr", "view"]:
                return _CommandResult(0, json.dumps({"state": "open", "reviewDecision": None}), "")
        if exe == "bash":
            return _CommandResult(0 if self.validation_ok else 1, "validation output", "")
        raise AssertionError(f"unexpected command in test: {cmd}")


@pytest.fixture
def fake_git(monkeypatch: pytest.MonkeyPatch) -> FakeGit:
    git = FakeGit()
    monkeypatch.setattr(pr_delivery, "_run", git)
    return git


async def _seed_project_and_task(db_engine, *, dirty_paths: list[str], pr_policy: str = "preferred"):
    """Creates a Project bound to a real (but git-uninitialized) temp
    directory plus a Task with a captured baseline, so eligibility only
    reflects paths dirtied *after* the baseline (`dirty_paths`).
    """
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    directory = tempfile.mkdtemp()
    async with session_local() as db:
        resource = DirectoryResource(name="Widgets", path=directory)
        db.add(resource)
        await db.flush()
        project = Project(
            name="Widgets",
            default_backend=AgentBackend.claude_code,
            primary_directory_id=resource.id,
            pr_policy=pr_policy,
        )
        db.add(project)
        await db.flush()
        task = Task(
            project_id=project.id,
            title="Add retry backoff",
            initial_prompt="Add retry backoff to the worker",
            backend=AgentBackend.claude_code,
            git_baseline_dirty_paths=[],
            git_baseline_captured_at=datetime.now(timezone.utc),
        )
        db.add(task)
        await db.commit()
        project_id, task_id = project.id, task.id

    async with session_local() as db:
        return await db.get(Project, project_id), await db.get(Task, task_id)


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(projects_routes.router, prefix="/api")
    app.include_router(pr_delivery_routes.router, prefix="/api")
    return app


# -- safety rejection paths --------------------------------------------------


@pytest.mark.asyncio
async def test_prepare_rejects_non_git_repo(db_engine, fake_git):
    fake_git.is_repo = False
    fake_git.dirty_paths = ["src/worker.py"]
    project, task = await _seed_project_and_task(db_engine, dirty_paths=[])

    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_local() as db:
        with pytest.raises(PrDeliveryError, match="not a Git repository"):
            await pr_delivery.prepare(db, task, project)


@pytest.mark.asyncio
async def test_prepare_rejects_missing_remote(db_engine, fake_git):
    fake_git.remote_url = None
    fake_git.dirty_paths = ["src/worker.py"]
    project, task = await _seed_project_and_task(db_engine, dirty_paths=[])

    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_local() as db:
        with pytest.raises(PrDeliveryError, match="remote is configured"):
            await pr_delivery.prepare(db, task, project)


@pytest.mark.asyncio
async def test_prepare_rejects_detached_head(db_engine, fake_git):
    fake_git.detached = True
    fake_git.dirty_paths = ["src/worker.py"]
    project, task = await _seed_project_and_task(db_engine, dirty_paths=[])

    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_local() as db:
        with pytest.raises(PrDeliveryError, match="detached HEAD"):
            await pr_delivery.prepare(db, task, project)


@pytest.mark.asyncio
async def test_prepare_rejects_no_eligible_changes(db_engine, fake_git):
    fake_git.dirty_paths = []
    project, task = await _seed_project_and_task(db_engine, dirty_paths=[])

    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_local() as db:
        with pytest.raises(PrDeliveryError, match="No eligible changes"):
            await pr_delivery.prepare(db, task, project)


@pytest.mark.asyncio
async def test_prepare_excludes_pre_existing_unrelated_changes(db_engine, fake_git):
    """Files already dirty before the task started must never be silently
    swept into the PR -- only files dirtied since the captured baseline are
    eligible, and everything else is reported as excluded.
    """
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    project, task = await _seed_project_and_task(db_engine, dirty_paths=[])
    async with session_local() as db:
        loaded = await db.get(Task, task.id)
        loaded.git_baseline_dirty_paths = ["README.md"]  # pre-existing, unrelated
        await db.commit()

    fake_git.dirty_paths = ["README.md", "src/worker.py"]  # README already dirty at baseline

    async with session_local() as db:
        loaded = await db.get(Task, task.id)
        run = await pr_delivery.prepare(db, loaded, project)

    assert run.file_paths == ["src/worker.py"]
    assert run.excluded_paths == ["README.md"]


@pytest.mark.asyncio
async def test_eligibility_reports_unknown_baseline_as_ineligible(db_engine, fake_git):
    """A task whose baseline was never captured must never be treated as if
    it started from a clean tree -- every dirty path is excluded, not eligible.
    """
    fake_git.dirty_paths = ["src/worker.py"]
    project, task = await _seed_project_and_task(db_engine, dirty_paths=[])
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_local() as db:
        loaded = await db.get(Task, task.id)
        loaded.git_baseline_captured_at = None
        await db.commit()
        loaded = await db.get(Task, task.id)
        result = await pr_delivery.eligibility(db, loaded, project)

    assert result["eligible"] is False
    assert result["eligible_paths"] == []
    assert result["excluded_paths"] == ["src/worker.py"]
    assert "baseline" in (result["reason"] or "")


def test_suggest_branch_name_never_collides_with_a_protected_branch():
    """Even a misconfigured (empty) branch prefix must never produce a name
    that collides with a protected branch -- the per-task suffix guarantees
    this structurally, which is what `prepare()`'s guard rail relies on.
    """

    class _Task:
        id = UUID("00000000-0000-0000-0000-000000000001")
        title = "main"

    for prefix in ("", "main", "  ", "muster/"):
        name = pr_delivery.suggest_branch_name(prefix, _Task())
        assert name.lower() not in pr_delivery._PROTECTED_BRANCHES


@pytest.mark.asyncio
async def test_eligibility_flags_a_protected_current_branch(db_engine, fake_git):
    """Surfacing that the *current* branch is protected lets the UI explain
    why a fresh feature branch will be created (requirement: never push
    directly from a protected/default branch).
    """
    fake_git.current_branch = "main"
    fake_git.dirty_paths = ["src/worker.py"]
    project, task = await _seed_project_and_task(db_engine, dirty_paths=[])
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_local() as db:
        loaded = await db.get(Task, task.id)
        result = await pr_delivery.eligibility(db, loaded, project)
    assert result["current_branch"] == "main"
    assert result["is_protected_branch"] is True


@pytest.mark.asyncio
async def test_confirm_always_checks_out_a_feature_branch_off_the_current_one(db_engine, fake_git):
    """Even when the working tree is currently on the protected default
    branch, confirm() must create/checkout the generated feature branch and
    never push straight to the current branch.
    """
    fake_git.current_branch = "main"
    fake_git.default_branch = "main"
    fake_git.dirty_paths = ["src/worker.py"]
    project, task = await _seed_project_and_task(db_engine, dirty_paths=[])
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_local() as db:
        loaded = await db.get(Task, task.id)
        run = await pr_delivery.prepare(db, loaded, project)
        result = await pr_delivery.confirm(db, loaded, project, run)

    assert result.status == PrDeliveryStatus.succeeded
    assert result.head_branch != "main"
    checkout_calls = [c for c in fake_git.calls if c[:2] == [settings.git_bin, "checkout"]]
    assert any(result.head_branch in c for c in checkout_calls)
    push_calls = [c for c in fake_git.calls if c[:2] == [settings.git_bin, "push"]]
    assert push_calls and push_calls[0][-1] == result.head_branch


# -- idempotency & duplicate-click handling ----------------------------------


@pytest.mark.asyncio
async def test_prepare_is_idempotent_across_rapid_repeated_clicks(db_engine, fake_git):
    fake_git.dirty_paths = ["src/worker.py"]
    project, task = await _seed_project_and_task(db_engine, dirty_paths=[])
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)

    async with session_local() as db:
        loaded = await db.get(Task, task.id)
        first = await pr_delivery.prepare(db, loaded, project)

    async with session_local() as db:
        loaded = await db.get(Task, task.id)
        second = await pr_delivery.prepare(db, loaded, project)

    assert first.id == second.id
    async with session_local() as db:
        runs = await pr_delivery.list_runs(db, task.id)
    assert len(runs) == 1


@pytest.mark.asyncio
async def test_confirm_on_terminal_run_is_a_no_op(db_engine, fake_git):
    """Calling confirm() again after a run already succeeded (double-click,
    or a retry after a backend restart) must not repeat any side effect.
    """
    fake_git.dirty_paths = ["src/worker.py"]
    project, task = await _seed_project_and_task(db_engine, dirty_paths=[])
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)

    async with session_local() as db:
        loaded = await db.get(Task, task.id)
        run = await pr_delivery.prepare(db, loaded, project)
        confirmed = await pr_delivery.confirm(db, loaded, project, run)
    assert confirmed.status == PrDeliveryStatus.succeeded
    calls_after_first_confirm = len(fake_git.calls)

    async with session_local() as db:
        loaded = await db.get(Task, task.id)
        reloaded_run = await pr_delivery.latest_run(db, task.id)
        second = await pr_delivery.confirm(db, loaded, project, reloaded_run)

    assert second.status == PrDeliveryStatus.succeeded
    assert second.pr_url == confirmed.pr_url
    assert len(fake_git.calls) == calls_after_first_confirm  # no repeated push/create


# -- full state machine + duplicate PR prevention ----------------------------


@pytest.mark.asyncio
async def test_confirm_full_flow_creates_pr_and_tags_task(db_engine, fake_git):
    fake_git.dirty_paths = ["src/worker.py"]
    project, task = await _seed_project_and_task(db_engine, dirty_paths=[])
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)

    async with session_local() as db:
        loaded = await db.get(Task, task.id)
        run = await pr_delivery.prepare(db, loaded, project)
        result = await pr_delivery.confirm(db, loaded, project, run)

    assert result.status == PrDeliveryStatus.succeeded
    assert result.pr_url == "https://github.com/acme/widgets/pull/42"
    assert result.pr_number == 42
    assert result.repository == "acme/widgets"

    async with session_local() as db:
        reloaded_task = await db.get(Task, task.id)
    assert "PR Raised" in reloaded_task.tags
    push_calls = [c for c in fake_git.calls if c[:2] == [settings.git_bin, "push"]]
    create_calls = [c for c in fake_git.calls if c[:3] == [settings.gh_bin, "pr", "create"]]
    assert len(push_calls) == 1
    assert len(create_calls) == 1


@pytest.mark.asyncio
async def test_confirm_links_existing_pr_instead_of_duplicating(db_engine, fake_git):
    """An existing open PR for the same head branch must be resumed/linked,
    never re-created."""
    fake_git.dirty_paths = ["src/worker.py"]
    fake_git.existing_pr = {
        "url": "https://github.com/acme/widgets/pull/7",
        "number": 7,
        "state": "OPEN",
    }
    project, task = await _seed_project_and_task(db_engine, dirty_paths=[])
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)

    async with session_local() as db:
        loaded = await db.get(Task, task.id)
        run = await pr_delivery.prepare(db, loaded, project)
        result = await pr_delivery.confirm(db, loaded, project, run)

    assert result.status == PrDeliveryStatus.succeeded
    assert result.pr_number == 7
    push_calls = [c for c in fake_git.calls if c[:2] == [settings.git_bin, "push"]]
    create_calls = [c for c in fake_git.calls if c[:3] == [settings.gh_bin, "pr", "create"]]
    assert push_calls == []
    assert create_calls == []


@pytest.mark.asyncio
async def test_validation_command_failure_marks_run_failed(db_engine, fake_git):
    fake_git.dirty_paths = ["src/worker.py"]
    fake_git.validation_ok = False
    project, task = await _seed_project_and_task(db_engine, dirty_paths=[])
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_local() as db:
        loaded_project = await db.get(Project, project.id)
        loaded_project.pr_validation_command = "npm test"
        await db.commit()
        loaded_task = await db.get(Task, task.id)
        run = await pr_delivery.prepare(db, loaded_task, loaded_project)
        result = await pr_delivery.confirm(db, loaded_task, loaded_project, run)

    assert result.status == PrDeliveryStatus.failed
    assert "Validation command failed" in (result.error_message or "")
    push_calls = [c for c in fake_git.calls if c[:2] == [settings.git_bin, "push"]]
    assert push_calls == []  # never pushes if validation fails


@pytest.mark.asyncio
async def test_confirm_fails_closed_when_tree_changed_since_prepare(db_engine, fake_git):
    fake_git.dirty_paths = ["src/worker.py"]
    project, task = await _seed_project_and_task(db_engine, dirty_paths=[])
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_local() as db:
        loaded = await db.get(Task, task.id)
        run = await pr_delivery.prepare(db, loaded, project)

    fake_git.dirty_paths = ["src/worker.py", "src/other.py"]  # changed after prepare

    async with session_local() as db:
        loaded = await db.get(Task, task.id)
        reloaded_run = await pr_delivery.latest_run(db, task.id)
        result = await pr_delivery.confirm(db, loaded, project, reloaded_run)

    assert result.status == PrDeliveryStatus.failed
    assert "changed since this PR was prepared" in (result.error_message or "")


# -- cancel / complete-without-pr / completion gate --------------------------


@pytest.mark.asyncio
async def test_cancel_rejects_an_awaiting_run(db_engine, fake_git):
    fake_git.dirty_paths = ["src/worker.py"]
    project, task = await _seed_project_and_task(db_engine, dirty_paths=[])
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_local() as db:
        loaded = await db.get(Task, task.id)
        run = await pr_delivery.prepare(db, loaded, project)
        cancelled = await pr_delivery.cancel(db, run)
    assert cancelled.status == PrDeliveryStatus.rejected

    async with session_local() as db:
        loaded = await db.get(Task, task.id)
        # A new prepare() must be allowed after a rejection, not blocked by
        # the old (now terminal) run.
        new_run = await pr_delivery.prepare(db, loaded, project)
    assert new_run.id != run.id


@pytest.mark.asyncio
async def test_complete_without_pr_satisfies_required_policy(db_engine, fake_git):
    project, task = await _seed_project_and_task(db_engine, dirty_paths=[], pr_policy="required")
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)

    async with session_local() as db:
        loaded_task, loaded_project = await db.get(Task, task.id), await db.get(Project, project.id)
        gate_before = await pr_delivery.get_completion_gate(db, loaded_task, loaded_project)
        assert gate_before["satisfied"] is False

        run = await pr_delivery.complete_without_pr(db, loaded_task, loaded_project, "Docs-only change, no code diff.")
        assert run.status == PrDeliveryStatus.rejected
        assert run.completion_reason == "Docs-only change, no code diff."

        gate_after = await pr_delivery.get_completion_gate(db, loaded_task, loaded_project)
    assert gate_after["satisfied"] is True
    assert gate_after["reason"] == "Docs-only change, no code diff."


@pytest.mark.asyncio
async def test_completion_gate_satisfied_by_succeeded_pr(db_engine, fake_git):
    fake_git.dirty_paths = ["src/worker.py"]
    project, task = await _seed_project_and_task(db_engine, dirty_paths=[], pr_policy="required")
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_local() as db:
        loaded_task, loaded_project = await db.get(Task, task.id), await db.get(Project, project.id)
        run = await pr_delivery.prepare(db, loaded_task, loaded_project)
        await pr_delivery.confirm(db, loaded_task, loaded_project, run)
        gate = await pr_delivery.get_completion_gate(db, loaded_task, loaded_project)
    assert gate == {"satisfied": True, "reason": None}


@pytest.mark.asyncio
async def test_manual_policy_never_surfaces_a_hint(db_engine, fake_git):
    fake_git.dirty_paths = ["src/worker.py"]
    project, task = await _seed_project_and_task(db_engine, dirty_paths=[], pr_policy="manual")
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_local() as db:
        loaded_task, loaded_project = await db.get(Task, task.id), await db.get(Project, project.id)
        hint = await pr_delivery.eligibility_hint(db, loaded_task, loaded_project)
    assert hint is None


@pytest.mark.asyncio
async def test_preferred_policy_surfaces_a_hint_when_eligible(db_engine, fake_git):
    fake_git.dirty_paths = ["src/worker.py"]
    project, task = await _seed_project_and_task(db_engine, dirty_paths=[], pr_policy="preferred")
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_local() as db:
        loaded_task, loaded_project = await db.get(Task, task.id), await db.get(Project, project.id)
        hint = await pr_delivery.eligibility_hint(db, loaded_task, loaded_project)
    assert hint == {"eligible_file_count": 1}


# -- API-layer wiring ---------------------------------------------------------


@pytest.mark.asyncio
async def test_api_prepare_confirm_round_trip(override_get_db, db_engine, fake_git):
    fake_git.dirty_paths = ["src/worker.py"]
    project, task = await _seed_project_and_task(db_engine, dirty_paths=[])

    app = _build_app()
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        eligibility_resp = await client.get(f"/api/tasks/{task.id}/pr-delivery/eligibility")
        assert eligibility_resp.status_code == 200
        assert eligibility_resp.json()["eligible"] is True

        prepare_resp = await client.post(f"/api/tasks/{task.id}/pr-delivery/prepare", json={})
        assert prepare_resp.status_code == 201
        run = prepare_resp.json()
        assert run["status"] == "awaiting_confirmation"
        assert run["file_paths"] == ["src/worker.py"]

        confirm_resp = await client.post(
            f"/api/tasks/{task.id}/pr-delivery/{run['id']}/confirm", json={}
        )
        assert confirm_resp.status_code == 200
        confirmed = confirm_resp.json()
        assert confirmed["status"] == "succeeded"
        assert confirmed["pr_number"] == 42

        list_resp = await client.get(f"/api/tasks/{task.id}/pr-delivery")
        assert list_resp.status_code == 200
        assert len(list_resp.json()["items"]) == 1


@pytest.mark.asyncio
async def test_api_prepare_rejects_with_422_when_unsafe(override_get_db, db_engine, fake_git):
    fake_git.remote_url = None
    project, task = await _seed_project_and_task(db_engine, dirty_paths=[])

    app = _build_app()
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(f"/api/tasks/{task.id}/pr-delivery/prepare", json={})
    assert resp.status_code == 422
    assert "remote" in resp.json()["detail"]


# -- integration with POST /tasks/{id}/complete (task-completion lifecycle) --
#
# `complete_task` in app/api/routes/tasks.py gates on
# `pr_delivery.get_completion_gate()` before calling
# `process_manager.complete()`. `process_manager.complete()` itself is
# mocked here (it opens its own module-level `SessionLocal`, a real Postgres
# connection unrelated to this test's in-memory sqlite engine) -- these
# tests only verify the gate decision at the route layer, not
# ProcessManager's own behavior.


@pytest.mark.asyncio
async def test_complete_task_blocked_when_pr_required_and_unsatisfied(override_get_db, db_engine, fake_git, monkeypatch):
    complete_mock = AsyncMock()
    monkeypatch.setattr(tasks_routes.process_manager, "complete", complete_mock)
    project, task = await _seed_project_and_task(db_engine, dirty_paths=[], pr_policy="required")

    app = _build_app()
    app.include_router(tasks_routes.router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(f"/api/tasks/{task.id}/complete")

    assert resp.status_code == 422
    assert "PR" in resp.json()["detail"] or "pr" in resp.json()["detail"].lower()
    complete_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_complete_task_allowed_after_complete_without_pr_override(override_get_db, db_engine, fake_git, monkeypatch):
    complete_mock = AsyncMock()
    monkeypatch.setattr(tasks_routes.process_manager, "complete", complete_mock)
    project, task = await _seed_project_and_task(db_engine, dirty_paths=[], pr_policy="required")

    app = _build_app()
    app.include_router(tasks_routes.router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        override_resp = await client.post(
            f"/api/tasks/{task.id}/pr-delivery/complete-without-pr",
            json={"reason": "Docs-only change, no code diff."},
        )
        assert override_resp.status_code == 200

        resp = await client.post(f"/api/tasks/{task.id}/complete")

    assert resp.status_code == 200
    complete_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_complete_task_allowed_by_default_preferred_policy(override_get_db, db_engine, fake_git, monkeypatch):
    """`preferred` (the default) never blocks completion -- only `required` does."""
    complete_mock = AsyncMock()
    monkeypatch.setattr(tasks_routes.process_manager, "complete", complete_mock)
    project, task = await _seed_project_and_task(db_engine, dirty_paths=[], pr_policy="preferred")

    app = _build_app()
    app.include_router(tasks_routes.router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(f"/api/tasks/{task.id}/complete")

    assert resp.status_code == 200
    complete_mock.assert_awaited_once()
