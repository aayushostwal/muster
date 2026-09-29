"""The remote event loop must create one task and resume it only for new comments."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
import uuid

import pytest
import httpx
from fastapi import FastAPI
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import (
    AgentBackend, DirectoryResource, IntegrationEvent, IntegrationSettings,
    JiraIssueLink, JiraProjectMapping, Message, MessageSender, Project, Task,
)
from app.services import integrations
from app.api.routes import integrations as integration_routes
from app.db.session import get_db


def test_integration_routes_reject_remote_clients_and_origins():
    local = Request({"type": "http", "client": ("127.0.0.1", 1234), "headers": []})
    integration_routes._require_local(local)
    remote = Request({"type": "http", "client": ("192.0.2.10", 1234), "headers": []})
    with pytest.raises(HTTPException) as denied:
        integration_routes._require_local(remote)
    assert denied.value.status_code == 403


class FakeJira:
    base = "https://jira.example.test"

    def __init__(self):
        self.issue_data = {"id": "10001", "key": "APP-1", "fields": {
            "summary": "Fix login", "description": "Login fails", "project": {"key": "APP"},
        }}
        self.issue_comments: list[dict] = [{"id": "10", "body": "Initial detail", "author": {"displayName": "Owner"}}]
        self.posted: list[str] = []
        self.created: list[tuple[str, str, str]] = []

    async def assigned_issues(self, since, until):
        return [self.issue_data]

    async def comments(self, key):
        return list(self.issue_comments)

    async def post_comment(self, key, body):
        self.posted.append(body)
        return {"id": str(100 + len(self.posted))}

    async def create_issue(self, project_key, title, description):
        self.created.append((project_key, title, description))
        return {"key": "APP-1"}

    async def issue(self, key):
        return self.issue_data


class FakeSlack:
    user_id = "U-ME"

    def __init__(self):
        self.message = {"ts": "1700000000.000001", "user": "U-OTHER",
                        "text": "<@U-ME> please fix login", "channel": {"id": "C1"},
                        "permalink": "https://slack.example.test/thread"}
        self.replies: list[dict] = []

    async def directed_messages(self, since, until):
        return [self.message]

    async def thread(self, channel, root_ts):
        return [self.message, *self.replies]


@pytest.mark.asyncio
async def test_jira_issue_link_comment_resume_and_outbound_dedupe(db_engine, monkeypatch):
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    triggered = []
    resumed = []

    async def trigger(task_id): triggered.append(task_id)
    async def resume(task_id): resumed.append(task_id)
    monkeypatch.setattr(integrations.process_manager, "trigger", trigger)
    monkeypatch.setattr(integrations.process_manager, "resume", resume)
    jira = FakeJira()
    now = datetime.now(timezone.utc)
    async with session_local() as db:
        directory = DirectoryResource(name="APP", path="/tmp/app")
        db.add(directory)
        await db.flush()
        project = Project(name="App", default_backend=AgentBackend.codex, primary_directory_id=directory.id)
        db.add(project)
        await db.flush()
        db.add(JiraProjectMapping(jira_project_key="APP", project_id=project.id))
        settings = IntegrationSettings(id=1)
        db.add(settings)
        await db.commit()

        await integrations._sync_jira(db, settings, jira, now)
        await integrations._sync_jira(db, settings, jira, now + timedelta(minutes=1))
        links = (await db.execute(select(JiraIssueLink))).scalars().all()
        tasks = (await db.execute(select(Task))).scalars().all()
        assert len(links) == len(tasks) == len(triggered) == 1
        assert "Initial detail" in tasks[0].initial_prompt
        assert resumed == []

        jira.issue_comments.append({"id": "11", "body": "Please check SSO too", "author": {"displayName": "Owner"}})
        await integrations._sync_jira(db, settings, jira, now + timedelta(minutes=2))
        await integrations._sync_jira(db, settings, jira, now + timedelta(minutes=3))
        assert resumed == [tasks[0].id]
        messages = (await db.execute(select(Message).where(Message.task_id == tasks[0].id))).scalars().all()
        assert len(messages) == 1 and "SSO" in messages[0].content_text

        db.add(Message(task_id=tasks[0].id, sender=MessageSender.agent, content_text="Question: Which SSO provider?"))
        await db.commit()
        await integrations._sync_jira(db, settings, jira, now + timedelta(minutes=4))
        await integrations._sync_jira(db, settings, jira, now + timedelta(minutes=5))
        assert jira.posted == ["Muster task update:\nQuestion: Which SSO provider?"]


@pytest.mark.asyncio
async def test_slack_thread_creates_one_jira_issue_and_ambiguous_goes_to_review(db_engine, monkeypatch):
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    triggered = []
    async def trigger(task_id): triggered.append(task_id)
    monkeypatch.setattr(integrations.process_manager, "trigger", trigger)
    jira = FakeJira()
    slack = FakeSlack()
    async with session_local() as db:
        directory = DirectoryResource(name="APP", path="/tmp/app")
        db.add(directory)
        await db.flush()
        project = Project(name="App", default_backend=AgentBackend.codex, primary_directory_id=directory.id)
        db.add(project)
        await db.flush()
        db.add(JiraProjectMapping(jira_project_key="APP", project_id=project.id))
        settings = IntegrationSettings(id=1, slack_jira_project_key="APP")
        db.add(settings)
        await db.commit()
        until = datetime.fromtimestamp(1700000001, timezone.utc)
        await integrations._sync_slack(db, settings, slack, jira, until)
        await integrations._sync_slack(db, settings, slack, jira, until + timedelta(minutes=1))
        assert len(jira.created) == len(triggered) == 1
        assert "https://slack.example.test/thread" in jira.created[0][2]
        slack.replies.append({"ts": "1700000020.000001", "user": "U-OTHER", "text": "Also check SSO"})
        await integrations._sync_slack(db, settings, slack, jira, until + timedelta(minutes=1))
        await integrations._sync_slack(db, settings, slack, jira, until + timedelta(minutes=2))
        assert jira.posted == ["Slack thread reply by U-OTHER:\nAlso check SSO"]
        slack.message = {**slack.message, "ts": "1700000000.000002", "thread_ts": "1700000000.000002", "text": "FYI, meeting moved"}
        await integrations._sync_slack(db, settings, slack, jira, until + timedelta(minutes=3))
        events = (await db.execute(select(IntegrationEvent).where(IntegrationEvent.status == "needs_review"))).scalars().all()
        assert len(events) == 1


@pytest.mark.asyncio
async def test_integration_config_keeps_tokens_private_and_validates_schedule(override_get_db, monkeypatch):
    monkeypatch.setattr(integration_routes, "sync_jobs_from_db", lambda: None)
    app = FastAPI()
    app.include_router(integration_routes.router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/integrations/config", headers={"Origin": "https://untrusted.example"})).status_code == 403
        assert (await client.patch("/api/integrations/config", json={"schedule_expr": "bad"})).status_code == 422
        assert (await client.patch("/api/integrations/config", json={"timezone": "Not/AZone"})).status_code == 422
        assert (await client.patch("/api/integrations/config", json={"enabled": True})).status_code == 422
        response = await client.patch("/api/integrations/config", json={
            "jira_base_url": "https://jira.example.test", "jira_email": "owner@example.test",
            "jira_token": "sensitive-token", "schedule_expr": "0 9 * * 1-5",
            "timezone": "Asia/Kolkata", "enabled": True,
        })
        assert response.status_code == 200
        assert response.json()["has_jira_token"] is True
        assert "sensitive-token" not in response.text
        assert "sensitive-token" not in (await client.get("/api/integrations/config")).text


@pytest.mark.asyncio
async def test_run_keeps_failed_source_cursor_and_advances_successful_source(db_engine, monkeypatch):
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(integrations, "engine", db_engine)
    monkeypatch.setattr(integrations, "SessionLocal", session_local)
    monkeypatch.setattr(integrations, "JiraClient", lambda settings, client: FakeJira())
    monkeypatch.setattr(integrations, "SlackClient", lambda settings, client: FakeSlack())

    async def fail_jira(db, settings, jira, until):
        raise integrations.RemoteError("temporary failure")

    async def succeed_slack(db, settings, slack, jira, until):
        settings.slack_cursor = until
        await db.commit()

    monkeypatch.setattr(integrations, "_sync_jira", fail_jira)
    monkeypatch.setattr(integrations, "_sync_slack", succeed_slack)
    async with session_local() as db:
        db.add(IntegrationSettings(id=1, enabled=True, slack_token=b"fake"))
        await db.commit()
    async with AsyncClient() as client:
        run = await integrations.run_integration_once(client=client)
    assert run.status == "failed"
    async with session_local() as db:
        config = await db.get(IntegrationSettings, 1)
        assert config.jira_cursor is None
        assert config.slack_cursor is not None
        assert config.last_status == "failed"


@pytest.mark.asyncio
async def test_jira_client_paginates_and_uses_adf_for_mutations(monkeypatch):
    monkeypatch.setattr(integrations, "decrypt_secret", lambda value: "jira-token")
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/search/jql"):
            if b"nextPageToken" in request.content:
                return httpx.Response(200, json={"issues": [{"id": "2"}]})
            return httpx.Response(200, json={"issues": [{"id": "1"}], "nextPageToken": "next"})
        if request.url.path.endswith("/comment") and request.method == "GET":
            start = request.url.params.get("startAt")
            return httpx.Response(200, json={"comments": [{"id": start}], "total": 2})
        if request.url.path.endswith("/comment"):
            return httpx.Response(201, json={"id": "42"})
        if request.url.path.endswith("/issue"):
            return httpx.Response(201, json={"key": "APP-1"})
        return httpx.Response(200, json={"id": "1", "key": "APP-1"})

    settings = IntegrationSettings(jira_base_url="https://jira.example.test", jira_email="owner@example.test", jira_token=b"encrypted")
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        jira = integrations.JiraClient(settings, client)
        now = datetime.now(timezone.utc)
        assert [item["id"] for item in await jira.assigned_issues(now - timedelta(hours=1), now)] == ["1", "2"]
        assert [item["id"] for item in await jira.comments("APP-1")] == ["0", "1"]
        assert (await jira.issue("APP-1"))["key"] == "APP-1"
        assert (await jira.create_issue("APP", "Title", "First\nSecond"))["key"] == "APP-1"
        assert (await jira.post_comment("APP-1", "Update"))["id"] == "42"
    assert all(request.url.host == "jira.example.test" for request in seen)
    assert json.loads(seen[-1].content)["body"]["type"] == "doc"


@pytest.mark.asyncio
async def test_jira_client_rejects_insecure_site_and_reports_remote_failure(monkeypatch):
    monkeypatch.setattr(integrations, "decrypt_secret", lambda value: "token")
    settings = IntegrationSettings(jira_base_url="http://jira.example.test", jira_email="owner@example.test", jira_token=b"encrypted")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(403))) as client:
        with pytest.raises(integrations.RemoteError, match="HTTPS"):
            integrations.JiraClient(settings, client)
        settings.jira_base_url = "https://jira.example.test"
        jira = integrations.JiraClient(settings, client)
        with pytest.raises(integrations.RemoteError, match="HTTP 403"):
            await jira.issue("APP-1")


@pytest.mark.asyncio
async def test_slack_client_scans_direct_messages_and_mentions_and_reads_thread(monkeypatch):
    monkeypatch.setattr(integrations, "decrypt_secret", lambda value: "slack-token")
    queries = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search.messages"):
            queries.append(request.url.params["query"])
            return httpx.Response(200, json={"ok": True, "messages": {"matches": [
                {"ts": "1700000000.000001", "channel": {"id": "C1"}, "text": "please fix"},
            ], "paging": {"pages": 1}}})
        if request.url.params.get("cursor"):
            return httpx.Response(200, json={"ok": True, "messages": [{"ts": "2"}], "response_metadata": {"next_cursor": ""}})
        return httpx.Response(200, json={"ok": True, "messages": [{"ts": "1"}], "response_metadata": {"next_cursor": "more"}})

    settings = IntegrationSettings(slack_token=b"encrypted", slack_user_id="U-ME")
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        slack = integrations.SlackClient(settings, client)
        since = datetime.fromtimestamp(1699999990, timezone.utc)
        until = datetime.fromtimestamp(1700000010, timezone.utc)
        assert len(await slack.directed_messages(since, until)) == 1
        assert [item["ts"] for item in await slack.thread("C1", "1")] == ["1", "2"]
    assert len(queries) == 3
    assert queries[0].startswith("to:me ") and queries[1].startswith('"<@U-ME>" ')
    assert queries[2].startswith("with:me is:thread ")


@pytest.mark.asyncio
async def test_slack_client_surfaces_permission_failure(monkeypatch):
    monkeypatch.setattr(integrations, "decrypt_secret", lambda value: "token")
    settings = IntegrationSettings(slack_token=b"encrypted", slack_user_id="U-ME")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": False, "error": "missing_scope"}))) as client:
        slack = integrations.SlackClient(settings, client)
        with pytest.raises(integrations.RemoteError, match="missing_scope"):
            await slack.thread("C1", "1")


@pytest.mark.asyncio
async def test_mapping_review_and_run_routes(db_engine, monkeypatch):
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(integration_routes.router, prefix="/api")

    async def get_test_db():
        async with session_local() as db:
            yield db

    app.dependency_overrides[get_db] = get_test_db
    monkeypatch.setattr(integration_routes, "JiraClient", lambda settings, client: FakeJira())
    monkeypatch.setattr(integration_routes, "sync_jobs_from_db", lambda: None)
    triggered = []
    async def trigger(task_id): triggered.append(task_id)
    monkeypatch.setattr(integrations.process_manager, "trigger", trigger)
    async def run(): return SimpleNamespace(id=uuid.uuid4(), status="succeeded", error=None)
    monkeypatch.setattr(integration_routes, "run_integration_once", run)

    async with session_local() as db:
        directory = DirectoryResource(name="APP", path="/tmp/app")
        db.add(directory)
        await db.flush()
        project = Project(name="App", default_backend=AgentBackend.codex, primary_directory_id=directory.id)
        db.add(project)
        db.add(IntegrationSettings(id=1, slack_jira_project_key="APP"))
        review = IntegrationEvent(source="slack_thread", external_id="C1:1700000000.000001", status="needs_review", detail="Slack thread: https://slack.example.test/thread\n\nU1: please fix login")
        pending = IntegrationEvent(source="slack_thread", external_id="C2:1700000000.000001", status="pending", detail="https://slack.example.test/other")
        db.add(review)
        db.add(pending)
        await db.commit()
        project_id, review_id, pending_id = project.id, review.id, pending.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/api/integrations/mappings", json={"jira_project_key": "APP", "project_id": str(uuid.uuid4())})).status_code == 404
        created = await client.post("/api/integrations/mappings", json={"jira_project_key": "APP", "project_id": str(project_id)})
        assert created.status_code == 201
        mapping_id = created.json()["id"]
        assert (await client.post("/api/integrations/mappings", json={"jira_project_key": "APP", "project_id": str(project_id)})).status_code == 409
        assert len((await client.get("/api/integrations/mappings")).json()["items"]) == 1
        assert len((await client.get("/api/integrations/review")).json()["items"]) == 2
        assert (await client.post("/api/integrations/run-now")).json()["status"] == "succeeded"
        assert (await client.post(f"/api/integrations/review/{pending_id}/create-ticket")).status_code == 409
        ticket = await client.post(f"/api/integrations/review/{review_id}/create-ticket")
        assert ticket.status_code == 200
        assert ticket.json()["issue_key"] == "APP-1"
        assert len(triggered) == 1
        linked = await client.post(f"/api/integrations/review/{pending_id}/link-ticket", json={"issue_key": "APP-1"})
        assert linked.status_code == 200
        assert linked.json()["task_id"] == ticket.json()["task_id"]
        assert (await client.get("/api/integrations/review")).json()["items"] == []
        assert (await client.post(f"/api/integrations/review/{review_id}/dismiss")).status_code == 404
        assert (await client.delete(f"/api/integrations/mappings/{mapping_id}")).status_code == 204
        assert (await client.delete(f"/api/integrations/mappings/{mapping_id}")).status_code == 404
