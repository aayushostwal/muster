from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from httpx import ASGITransport, AsyncClient

from app.db.models import AgentBackend, CronJob, JiraIssueLink, Project, Task, TaskStatus, TaskSourceEvent, TaskSourceLink
from sqlalchemy import select
from app.services import cron_scheduler
from app.services.process_manager import process_manager
from app.services.recurring_schedule import WindowIntervalTrigger, in_run_window
from app.schemas.cron import RunWindow
from tests.test_tasks_api import _build_app


@pytest.mark.asyncio
@pytest.mark.parametrize("status", list(TaskStatus))
async def test_source_key_reuses_task_in_every_status(db_engine, override_get_db, monkeypatch, status):
    trigger = AsyncMock()
    monkeypatch.setattr(process_manager, "trigger", trigger)
    app = _build_app(override_get_db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        project = (await client.post("/api/projects", json={"name": "Intake", "default_backend": "claude_code"})).json()
        path = f"/api/projects/{project['id']}/tasks"
        body = {"title": "Fix issue", "initial_prompt": "work", "source_key": " jira:10001 "}
        created = await client.post(path, json=body)
        assert created.status_code == 201
        async with async_sessionmaker(db_engine, expire_on_commit=False)() as db:
            task = await db.get(Task, uuid.UUID(created.json()["id"]))
            task.status = status
            await db.commit()
        repeated = await client.post(path, json={**body, "title": "New title"})
        assert repeated.status_code == 200
        assert repeated.json()["id"] == created.json()["id"]
        assert repeated.json()["title"] == "Fix issue"
        assert repeated.json()["status"] == status.value
        assert repeated.json()["source_key"] == "jira:10001"
        trigger.assert_awaited_once()

        # A different item, a different project, and unkeyed manual tasks remain independent.
        distinct = await client.post(path, json={**body, "source_key": "jira:10002"})
        assert distinct.status_code == 201
        other = (await client.post("/api/projects", json={"name": "Other", "default_backend": "codex"})).json()
        assert (await client.post(f"/api/projects/{other['id']}/tasks", json=body)).status_code == 201
        for _ in range(2):
            assert (await client.post(path, json={"title": "Manual", "initial_prompt": "work"})).status_code == 201
        assert len((await client.get(path)).json()["items"]) == 4
        assert (await client.post(path, json={**body, "source_key": " "})).status_code == 422


@pytest.mark.asyncio
async def test_source_key_database_conflict_returns_winner(override_get_db, monkeypatch):
    trigger = AsyncMock()
    monkeypatch.setattr(process_manager, "trigger", trigger)
    app = _build_app(override_get_db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        project = (await client.post("/api/projects", json={"name": "Race", "default_backend": "codex"})).json()
        path = f"/api/projects/{project['id']}/tasks"
        body = {"title": "Intake", "initial_prompt": "work", "source_key": "slack:C1:123.456"}
        created = await client.post(path, json=body)
        original = AsyncSession.execute
        hidden = 0
        async def stale_read(self, statement, *args, **kwargs):
            nonlocal hidden
            if hidden < 2 and any(clause in str(statement) for clause in ("tasks.source_key =", "task_source_links.source_key =")):
                hidden += 1
                return SimpleNamespace(scalar_one_or_none=lambda: None)
            return await original(self, statement, *args, **kwargs)
        monkeypatch.setattr(AsyncSession, "execute", stale_read)
        duplicate = await client.post(path, json=body)
        assert hidden == 2
        assert duplicate.status_code == 200
        assert duplicate.json()["id"] == created.json()["id"]
        assert len((await client.get(path)).json()["items"]) == 1
        trigger.assert_awaited_once()


@pytest.mark.asyncio
async def test_slack_alias_and_unique_updates_continue_existing_jira_task(db_engine, override_get_db, monkeypatch):
    trigger, resume = AsyncMock(), AsyncMock()
    monkeypatch.setattr(process_manager, "trigger", trigger)
    monkeypatch.setattr(process_manager, "resume", resume)
    async with AsyncClient(transport=ASGITransport(app=_build_app(override_get_db)), base_url="http://test") as client:
        project = (await client.post("/api/projects", json={"name": "Linked", "default_backend": "codex"})).json()
        path = f"/api/projects/{project['id']}/tasks"
        body = {"title": "Fix login", "initial_prompt": "Work on APP-1", "source_key": "jira:10001"}
        original = (await client.post(path, json=body)).json()
        async with async_sessionmaker(db_engine, expire_on_commit=False)() as db:
            task = await db.get(Task, uuid.UUID(original["id"]))
            task.status = TaskStatus.done
            await db.commit()
        update = {**body, "source_key": "slack:C1:100.001", "related_source_key": "jira:10001", "source_event_key": "slack:C1:101.001", "source_update": "Also support SSO"}
        linked = await client.post(path, json=update)
        assert linked.status_code == 200 and linked.json()["id"] == original["id"]
        assert (await client.post(path, json=update)).json()["id"] == original["id"]
        resume.assert_awaited_once_with(uuid.UUID(original["id"]))
        # Later polls need only the saved Slack alias, not the Jira mapping again.
        update.pop("related_source_key")
        update.update(source_event_key="slack:C1:102.001", source_update="Use Okta")
        assert (await client.post(path, json=update)).json()["id"] == original["id"]
        assert (await client.post(path, json=update)).status_code == 200
        assert resume.await_count == 2
        trigger.assert_awaited_once()
        messages = (await client.get(f"/api/tasks/{original['id']}/messages")).json()["items"]
        assert [message["content_text"] for message in messages] == ["Also support SSO", "Use Okta"]
        assert len((await client.get(path)).json()["items"]) == 1
        other = await client.post(path, json={**body, "source_key": "jira:10002"})
        assert other.status_code == 201
        assert (await client.post(path, json={**update, "related_source_key": "jira:10002"})).status_code == 409
        assert (await client.post(path, json={**update, "related_source_key": "jira:missing"})).status_code == 404
        for invalid in ({"source_event_key": "event"}, {"source_update": "text"}, {"source_key": None, "related_source_key": "jira:10001"}):
            assert (await client.post(path, json={**body, **invalid})).status_code == 422


@pytest.mark.asyncio
async def test_source_update_retries_failed_dispatch_without_duplicate_message(override_get_db, monkeypatch):
    trigger, resume = AsyncMock(), AsyncMock(side_effect=[RuntimeError("runtime unavailable"), None])
    monkeypatch.setattr(process_manager, "trigger", trigger)
    monkeypatch.setattr(process_manager, "resume", resume)
    async with AsyncClient(transport=ASGITransport(app=_build_app(override_get_db)), base_url="http://test") as client:
        project = (await client.post("/api/projects", json={"name": "Retry", "default_backend": "codex"})).json()
        path = f"/api/projects/{project['id']}/tasks"
        body = {"title": "Task", "initial_prompt": "work", "source_key": "slack:C1:100"}
        task = (await client.post(path, json=body)).json()
        update = {**body, "source_event_key": "slack:C1:101", "source_update": "New reply"}
        with pytest.raises(RuntimeError, match="runtime unavailable"):
            await client.post(path, json=update)
        assert (await client.post(path, json=update)).status_code == 200
        assert (await client.post(path, json=update)).status_code == 200
        assert resume.await_count == 2
        assert len((await client.get(f"/api/tasks/{task['id']}/messages")).json()["items"]) == 1


@pytest.mark.asyncio
async def test_source_link_reuses_historical_jira_integration_task(db_engine, override_get_db, monkeypatch):
    trigger, resume = AsyncMock(), AsyncMock()
    monkeypatch.setattr(process_manager, "trigger", trigger)
    monkeypatch.setattr(process_manager, "resume", resume)
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as db:
        project = Project(name="Historical", default_backend=AgentBackend.codex)
        db.add(project)
        await db.flush()
        task = Task(project_id=project.id, title="APP-1", initial_prompt="work", backend=AgentBackend.codex)
        db.add(task)
        await db.flush()
        db.add(JiraIssueLink(issue_id="10001", issue_key="APP-1", task_id=task.id))
        await db.commit()
        project_id, task_id = project.id, task.id
    async with AsyncClient(transport=ASGITransport(app=_build_app(override_get_db)), base_url="http://test") as client:
        body = {"title": "Slack", "initial_prompt": "work", "source_key": "slack:C1:100", "related_source_key": "jira:APP-1", "source_event_key": "slack:C1:101", "source_update": "Check SSO"}
        response = await client.post(f"/api/projects/{project_id}/tasks", json=body)
        assert response.status_code == 200 and response.json()["id"] == str(task_id)
        trigger.assert_not_awaited()
        resume.assert_awaited_once_with(task_id)


@pytest.mark.asyncio
async def test_first_source_update_is_recorded_before_first_dispatch(db_engine, override_get_db, monkeypatch):
    trigger = AsyncMock()
    monkeypatch.setattr(process_manager, "trigger", trigger)
    async with AsyncClient(transport=ASGITransport(app=_build_app(override_get_db)), base_url="http://test") as client:
        project = (await client.post("/api/projects", json={"name": "New", "default_backend": "codex"})).json()
        body = {"title": "New item", "initial_prompt": "work", "source_key": "slack:C2:100", "source_event_key": "slack:C2:100", "source_update": "Fix login"}
        response = await client.post(f"/api/projects/{project['id']}/tasks", json=body)
        assert response.status_code == 201
        assert "Fix login" in response.json()["initial_prompt"]
        async with async_sessionmaker(db_engine, expire_on_commit=False)() as db:
            events = (await db.execute(select(TaskSourceEvent))).scalars().all()
            assert len(events) == 1 and events[0].status == "delivered"
            assert len((await db.execute(select(TaskSourceLink))).scalars().all()) == 1
        trigger.assert_awaited_once()


def utc(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def test_daily_window_intervals_reset_at_opening_and_exclude_close():
    trigger = WindowIntervalTrigger(90, "11:00", "21:00", "Asia/Kolkata")
    opening = trigger.get_next_fire_time(None, utc("2026-09-30T04:00:00"))
    assert opening == utc("2026-09-30T05:30:00")
    assert trigger.get_next_fire_time(opening, opening) == utc("2026-09-30T07:00:00")
    last = utc("2026-09-30T14:30:00")
    assert trigger.get_next_fire_time(last, last) == utc("2026-10-01T05:30:00")
    job = SimpleNamespace(window_start="11:00", window_end="21:00", timezone="Asia/Kolkata")
    assert in_run_window(job, opening)
    assert not in_run_window(job, utc("2026-09-30T15:30:00"))


def test_overnight_window_and_timezone_validation():
    trigger = WindowIntervalTrigger(60, "22:00", "02:00", "Asia/Kolkata")
    assert trigger.get_next_fire_time(None, utc("2026-09-30T19:00:00")) == utc("2026-09-30T19:30:00")
    job = SimpleNamespace(window_start="22:00", window_end="02:00", timezone="Asia/Kolkata")
    assert in_run_window(job, utc("2026-09-30T19:00:00"))
    assert not in_run_window(job, utc("2026-09-30T21:00:00"))
    for values in ({"timezone": "invalid"}, {"window_start": "11:00"}, {"window_start": "25:00", "window_end": "21:00"}, {"window_start": "11:00", "window_end": "11:00"}):
        with pytest.raises(ValueError):
            RunWindow.model_validate(values)


@pytest.mark.asyncio
async def test_scheduler_skips_outside_window_but_manual_run_bypasses_it(db_engine, monkeypatch):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(cron_scheduler, "SessionLocal", session_factory)
    trigger = AsyncMock()
    monkeypatch.setattr(cron_scheduler.process_manager, "trigger", trigger)
    clock = SimpleNamespace(now=lambda tz: utc("2026-09-30T02:00:00"))
    monkeypatch.setattr(cron_scheduler, "datetime", clock)
    async with session_factory() as db:
        project = Project(name="Window", default_backend=AgentBackend.claude_code)
        db.add(project)
        await db.flush()
        job = CronJob(project_id=project.id, name="Triage", schedule_expr="0 * * * *", prompt="triage", backend=AgentBackend.claude_code,
                      timezone="Asia/Kolkata", window_start="11:00", window_end="21:00")
        db.add(job)
        await db.commit()
        job_id = job.id
    assert await cron_scheduler._fire_cron_job(job_id) is None
    trigger.assert_not_awaited()
    assert await cron_scheduler._fire_cron_job(job_id, allow_disabled=True) is not None
    trigger.assert_awaited_once()
    clock.now = lambda tz: utc("2026-09-30T05:30:00")
    assert await cron_scheduler._fire_cron_job(job_id) is not None
    assert trigger.await_count == 2


@pytest.mark.asyncio
async def test_explicit_legacy_task_mapping_is_project_scoped(override_get_db, monkeypatch):
    monkeypatch.setattr(process_manager, "trigger", AsyncMock())
    resume = AsyncMock()
    monkeypatch.setattr(process_manager, "resume", resume)
    async with AsyncClient(transport=ASGITransport(app=_build_app(override_get_db)), base_url="http://test") as client:
        project = (await client.post("/api/projects", json={"name": "Legacy", "default_backend": "codex"})).json()
        path = f"/api/projects/{project['id']}/tasks"
        legacy = (await client.post(path, json={"title": "APP-1", "initial_prompt": "Fix APP-1"})).json()
        body = {"title": "Slack", "initial_prompt": "work", "source_key": "slack:C1:100", "related_task_id": legacy["id"], "related_source_key": "jira:APP-1", "source_event_key": "slack:C1:101", "source_update": "Use Okta"}
        response = await client.post(path, json=body)
        assert response.status_code == 200 and response.json()["id"] == legacy["id"]
        assert (await client.post(path, json=body)).status_code == 200
        resume.assert_awaited_once_with(uuid.UUID(legacy["id"]))
        jira_repeat = await client.post(path, json={"title": "APP-1", "initial_prompt": "work", "source_key": "jira:APP-1"})
        assert jira_repeat.json()["id"] == legacy["id"]
        other = (await client.post("/api/projects", json={"name": "Other", "default_backend": "codex"})).json()
        assert (await client.post(f"/api/projects/{other['id']}/tasks", json=body)).status_code == 404
        assert (await client.post(path, json={**body, "related_task_id": str(uuid.uuid4())})).status_code == 404
        assert (await client.post(path, json={**body, "source_key": None})).status_code == 422
