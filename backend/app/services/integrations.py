"""Jira/Slack polling and the durable issue-to-task conversation bridge."""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlparse

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt_secret
from app.db.models import (
    IntegrationEvent, IntegrationRun, IntegrationSettings, JiraIssueLink,
    JiraProjectMapping, Message, MessageSender, PrDeliveryRun, TaskSourceEvent,
    PrDeliveryStatus, Project, RuntimeMode, Task, TaskStatus,
)
from app.db.session import SessionLocal, engine
from app.services.process_manager import process_manager
from app.services import task_sources

logger = logging.getLogger(__name__)
_local_lock = asyncio.Lock()
_advisory_lock_id = 7318421
_MAX_TEXT = 12000


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _adf_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        text_part = value.get("text", "")
        children = value.get("content", [])
        return str(text_part) + "".join(_adf_text(child) for child in children)
    if isinstance(value, list):
        return "\n".join(_adf_text(item) for item in value)
    return ""


def _adf(value: str) -> dict:
    return {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": line or " "}]}
        for line in value.splitlines() or [""]
    ]}


class RemoteError(RuntimeError):
    pass


class JiraClient:
    def __init__(self, settings: IntegrationSettings, client: httpx.AsyncClient):
        if not settings.jira_base_url or not settings.jira_email or not settings.jira_token:
            raise RemoteError("Jira URL, email, and token are required")
        parsed = urlparse(settings.jira_base_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise RemoteError("Jira URL must be an HTTPS site URL")
        self.base = settings.jira_base_url.rstrip("/")
        self.auth = (settings.jira_email, decrypt_secret(settings.jira_token))
        self.client = client

    async def request(self, method: str, path: str, **kwargs) -> dict:
        for attempt in range(3):
            response = await self.client.request(
                method, self.base + "/rest/api/3" + path,
                auth=self.auth, headers={"Accept": "application/json"}, **kwargs,
            )
            if response.status_code == 429 and attempt < 2:
                await asyncio.sleep(min(int(response.headers.get("Retry-After", "1")), 30))
                continue
            if response.is_error:
                raise RemoteError(f"Jira {method} {path}: HTTP {response.status_code}")
            return response.json() if response.content else {}
        raise RemoteError("Jira rate limit persisted")

    async def assigned_issues(self, since: datetime, until: datetime) -> list[dict]:
        # Jira search is eventually consistent; the overlap and issue IDs handle repeats.
        jql = f'assignee = currentUser() AND updated >= "{since:%Y-%m-%d %H:%M}" AND updated <= "{until:%Y-%m-%d %H:%M}" ORDER BY updated ASC'
        result = []
        token = None
        while True:
            body = {"jql": jql, "fields": ["summary", "description", "project", "assignee", "updated"], "maxResults": 100}
            if token:
                body["nextPageToken"] = token
            page = await self.request("POST", "/search/jql", json=body)
            result.extend(page.get("issues", []))
            token = page.get("nextPageToken")
            if not token:
                return result

    async def issue(self, key: str) -> dict:
        return await self.request("GET", f"/issue/{quote(key, safe='')}", params={"fields": "summary,description,project,assignee"})

    async def comments(self, key: str) -> list[dict]:
        result = []
        start = 0
        while True:
            page = await self.request("GET", f"/issue/{quote(key, safe='')}/comment", params={"startAt": start, "maxResults": 100})
            values = page.get("comments", [])
            result.extend(values)
            start += len(values)
            if not values or start >= page.get("total", start):
                return result

    async def create_issue(self, project_key: str, title: str, description: str) -> dict:
        return await self.request("POST", "/issue", json={"fields": {
            "project": {"key": project_key}, "issuetype": {"name": "Task"},
            "summary": title[:255], "description": _adf(description[:_MAX_TEXT]),
        }})

    async def post_comment(self, key: str, body: str) -> dict:
        return await self.request("POST", f"/issue/{quote(key, safe='')}/comment", json={"body": _adf(body[:_MAX_TEXT])})


class SlackClient:
    def __init__(self, settings: IntegrationSettings, client: httpx.AsyncClient):
        if not settings.slack_token or not settings.slack_user_id:
            raise RemoteError("Slack user token and user ID are required")
        self.token = decrypt_secret(settings.slack_token)
        self.user_id = settings.slack_user_id
        self.client = client

    async def request(self, method: str, params: dict) -> dict:
        for attempt in range(3):
            response = await self.client.get(
                "https://slack.com/api/" + method, params=params,
                headers={"Authorization": f"Bearer {self.token}"},
            )
            if response.status_code == 429 and attempt < 2:
                await asyncio.sleep(min(int(response.headers.get("Retry-After", "1")), 30))
                continue
            if response.is_error:
                raise RemoteError(f"Slack {method}: HTTP {response.status_code}")
            data = response.json()
            if not data.get("ok"):
                raise RemoteError(f"Slack {method}: {data.get('error', 'unknown error')}")
            return data
        raise RemoteError("Slack rate limit persisted")

    async def directed_messages(self, since: datetime, until: datetime) -> list[dict]:
        # Search includes replies whose parent predates the polling window.
        window = f"after:{(since - timedelta(days=1)):%Y-%m-%d} before:{(until + timedelta(days=1)):%Y-%m-%d}"
        result: dict[str, dict] = {}
        for term in ("to:me", f'"<@{self.user_id}>"', "with:me is:thread"):
            page = 1
            while True:
                data = await self.request("search.messages", {"query": f"{term} {window}", "count": 100, "page": page, "sort": "timestamp", "sort_dir": "asc"})
                matches = data.get("messages", {}).get("matches", [])
                for item in matches:
                    if since.timestamp() < float(item.get("ts", 0)) <= until.timestamp():
                        result[f"{item.get('channel', {}).get('id')}:{item.get('ts')}"] = item
                paging = data.get("messages", {}).get("paging", {})
                if page >= paging.get("pages", 1):
                    break
                page += 1
                if page > 100:
                    raise RemoteError("Slack search exceeded 100 pages; cursor was not advanced")
        return sorted(result.values(), key=lambda item: float(item["ts"]))

    async def thread(self, channel: str, root_ts: str) -> list[dict]:
        result = []
        cursor = None
        while True:
            params = {"channel": channel, "ts": root_ts, "limit": 100}
            if cursor:
                params["cursor"] = cursor
            data = await self.request("conversations.replies", params)
            result.extend(data.get("messages", []))
            cursor = data.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                return result


def _looks_actionable(text: str) -> bool:
    value = re.sub(r"<@[^>]+>", "", text).strip().lower()
    return bool(re.search(r"\b(please|can you|could you|need you to|todo|action item|fix|implement|create|update|investigate|review)\b", value))


async def _event(db: AsyncSession, source: str, external_id: str) -> IntegrationEvent | None:
    return (await db.execute(select(IntegrationEvent).where(IntegrationEvent.source == source, IntegrationEvent.external_id == external_id))).scalar_one_or_none()


async def _record(db: AsyncSession, source: str, external_id: str, status: str, detail: str | None = None) -> None:
    db.add(IntegrationEvent(source=source, external_id=external_id, status=status, detail=detail))
    await db.commit()


async def _ensure_issue_task(db: AsyncSession, jira: JiraClient, issue: dict) -> tuple[JiraIssueLink | None, bool]:
    issue_id = str(issue["id"])
    link = (await db.execute(select(JiraIssueLink).where(JiraIssueLink.issue_id == issue_id))).scalar_one_or_none()
    if link:
        return link, False
    key = issue["key"]
    project_key = issue.get("fields", {}).get("project", {}).get("key", key.split("-")[0])
    mapping = (await db.execute(select(JiraProjectMapping).where(JiraProjectMapping.jira_project_key == project_key))).scalar_one_or_none()
    if not mapping:
        if not await _event(db, "jira_unmapped", issue_id):
            await _record(db, "jira_unmapped", issue_id, "needs_review", key)
        return None, False
    project = await db.get(Project, mapping.project_id)
    if not project or not project.primary_directory_id:
        raise RemoteError(f"Mapped Muster project for {key} needs a primary directory")
    fields = issue.get("fields", {})
    comments = await jira.comments(key)
    discussion = "\n".join(f"- {_adf_text(c.get('body'))}" for c in comments)
    prompt = (
        f"Work on Jira {key}: {fields.get('summary', key)}\n"
        f"Jira URL: {jira.base}/browse/{quote(key, safe='')}\n\n"
        f"Description:\n{_adf_text(fields.get('description'))[:_MAX_TEXT]}\n\n"
        f"Discussion:\n{discussion[:_MAX_TEXT]}\n\n"
        "Implement the request in this project's repository. Ask blocking questions in the task. "
        "Make focused changes in the project repository. Do not push directly; Muster will use "
        "the project's PR delivery workflow after your turn finishes."
    )
    task = await task_sources.find_task(db, project.id, f"jira:{issue_id}")
    created = task is None
    if created:
        task = Task(project_id=project.id, source_key=f"jira:{issue_id}", title=f"[{key}] {fields.get('summary', key)}"[:300], initial_prompt=prompt,
                    backend=project.default_backend, model=project.default_model,
                    runtime_mode=RuntimeMode.structured, status=TaskStatus.queued)
        db.add(task)
        await db.flush()
    await task_sources.bind_source(db, task, f"jira:{issue_id}")
    await task_sources.bind_source(db, task, f"jira:{key}")
    link = JiraIssueLink(issue_id=issue_id, issue_key=key, task_id=task.id)
    db.add(link)
    db.add(IntegrationEvent(source="jira_task_start", external_id=issue_id, status="pending" if created else "processed"))
    for comment in comments if created else []:
        db.add(IntegrationEvent(source="jira_comment_in", external_id=str(comment["id"]), status="processed"))
    await db.commit()
    return link, created


async def _start_task_if_pending(db: AsyncSession, link: JiraIssueLink) -> None:
    event = await _event(db, "jira_task_start", link.issue_id)
    if event is None or event.status != "pending":
        return
    await process_manager.trigger(link.task_id)
    event.status = "processed"
    await db.commit()


async def _sync_issue_comments(db: AsyncSession, jira: JiraClient, link: JiraIssueLink) -> None:
    pending_ids: list[str] = []
    for comment in await jira.comments(link.issue_key):
        external_id = str(comment["id"])
        existing = await _event(db, "jira_comment_in", external_id)
        if existing:
            if existing.status == "pending":
                pending_ids.append(external_id)
            continue
        if await _event(db, "jira_comment_out", external_id):
            continue
        content = _adf_text(comment.get("body")).strip()
        if not content:
            continue
        author = comment.get("author", {}).get("displayName", "Jira user")
        db.add(Message(task_id=link.task_id, sender=MessageSender.user,
                       content_text=f"Jira comment by {author} ({link.issue_key}):\n{content[:_MAX_TEXT]}"))
        db.add(IntegrationEvent(source="jira_comment_in", external_id=external_id, status="pending"))
        await db.commit()
        pending_ids.append(external_id)
    if pending_ids:
        await process_manager.resume(link.task_id)
        pending = (await db.execute(select(IntegrationEvent).where(
            IntegrationEvent.source == "jira_comment_in", IntegrationEvent.external_id.in_(pending_ids),
        ))).scalars().all()
        for event in pending:
            event.status = "processed"
        await db.commit()


async def _post_task_updates(db: AsyncSession, jira: JiraClient, link: JiraIssueLink) -> None:
    from app.services import pr_delivery

    task = await db.get(Task, link.task_id)
    if task and task.status == TaskStatus.waiting_on_you and task.attention_reason == "awaiting_review":
        prior = (await db.execute(select(PrDeliveryRun).where(PrDeliveryRun.task_id == task.id))).scalars().all()
        if not prior:
            project = await db.get(Project, task.project_id)
            try:
                prepared = await pr_delivery.prepare(db, task, project)
                await pr_delivery.confirm(db, task, project, prepared)
            except pr_delivery.PrDeliveryError as exc:
                logger.info("PR delivery for Jira %s needs review: %s", link.issue_key, exc)
    messages = (await db.execute(select(Message).where(Message.task_id == link.task_id, Message.sender == MessageSender.agent).order_by(Message.created_at))).scalars().all()
    for message in messages:
        content = (message.content_text or "").strip()
        if not content or len(content) > _MAX_TEXT or re.search(r"(?i)(api[_ -]?key|secret|password|token)\s*[:=]", content):
            continue
        marker = str(message.id)
        if await _event(db, "task_message_out", marker):
            continue
        await _record(db, "task_message_out", marker, "pending", link.issue_key)
        posted = await jira.post_comment(link.issue_key, f"Muster task update:\n{content}")
        await _record(db, "jira_comment_out", str(posted["id"]), "processed", link.issue_key)
        event = await _event(db, "task_message_out", marker)
        event.status = "processed"
        await db.commit()
    runs = (await db.execute(select(PrDeliveryRun).where(PrDeliveryRun.task_id == link.task_id, PrDeliveryRun.status == PrDeliveryStatus.succeeded))).scalars().all()
    for run in runs:
        if not run.pr_url or await _event(db, "pr_out", str(run.id)):
            continue
        await _record(db, "pr_out", str(run.id), "pending", link.issue_key)
        posted = await jira.post_comment(link.issue_key, f"Muster created a PR: {run.pr_url}")
        await _record(db, "jira_comment_out", str(posted["id"]), "processed", link.issue_key)
        event = await _event(db, "pr_out", str(run.id))
        event.status = "processed"
        await db.commit()


async def _sync_jira(db: AsyncSession, settings: IntegrationSettings, jira: JiraClient, until: datetime) -> None:
    since = _aware(settings.jira_cursor or (until - timedelta(hours=24))) - timedelta(minutes=5)
    issues = await jira.assigned_issues(since, until)
    for issue in issues:
        link, created = await _ensure_issue_task(db, jira, issue)
        if link:
            await _start_task_if_pending(db, link)
    unmapped = (await db.execute(select(IntegrationEvent).where(
        IntegrationEvent.source == "jira_unmapped", IntegrationEvent.status == "needs_review"
    ))).scalars().all()
    for event in unmapped:
        issue = await jira.issue(event.detail)
        link, created = await _ensure_issue_task(db, jira, issue)
        if link:
            event.status = "processed"
            await db.commit()
            await _start_task_if_pending(db, link)
    links = (await db.execute(select(JiraIssueLink))).scalars().all()
    for link in links:
        await _start_task_if_pending(db, link)
        await _sync_issue_comments(db, jira, link)
        await _post_task_updates(db, jira, link)
    settings.jira_cursor = until
    await db.commit()


async def _append_slack_update(db: AsyncSession, link: JiraIssueLink, thread_key: str, event_key: str, content: str) -> None:
    task = await db.get(Task, link.task_id)
    if task is None:
        return
    async with task_sources.lock_for(task.project_id):
        await task_sources.bind_source(db, task, f"slack:{thread_key}")
        event = await task_sources.record_update(db, task, f"slack:{event_key}", content)
        await db.commit()
        await task_sources.dispatch_update(db, event)


async def _sync_slack(db: AsyncSession, settings: IntegrationSettings, slack: SlackClient, jira: JiraClient, until: datetime) -> None:
    if not settings.slack_jira_project_key:
        raise RemoteError("Choose a Jira project for Slack-created tickets")
    since = _aware(settings.slack_cursor or (until - timedelta(hours=24))) - timedelta(minutes=5)
    messages = await slack.directed_messages(since, until)
    for item in messages:
        channel = item.get("channel", {}).get("id")
        root_ts = item.get("thread_ts") or item.get("ts")
        if not channel or not root_ts or item.get("user") == slack.user_id:
            continue
        external_id = f"{channel}:{root_ts}"
        previous = await _event(db, "slack_thread", external_id)
        if previous:
            if previous.status == "pending" and previous.detail and re.fullmatch(r"[A-Z][A-Z0-9_]*-\d+", previous.detail):
                full_issue = await jira.issue(previous.detail)
                link, created = await _ensure_issue_task(db, jira, full_issue)
                if link:
                    previous.status = "processed"
                    await db.commit()
                    await _start_task_if_pending(db, link)
            continue
        thread = await slack.thread(channel, root_ts)
        transcript = "\n".join(f"{m.get('user', 'unknown')}: {m.get('text', '')}" for m in thread)
        permalink = item.get("permalink") or f"https://slack.com/app_redirect?channel={quote(channel)}&message_ts={quote(root_ts)}"
        references = set(re.findall(r"\b[A-Z][A-Z0-9_]*-\d+\b", transcript))
        if len(references) == 1:
            full_issue = await jira.issue(next(iter(references)))
            link, created = await _ensure_issue_task(db, jira, full_issue)
            if link:
                await _record(db, "slack_thread", external_id, "processed", link.issue_key)
                await _start_task_if_pending(db, link)
                root = next((message for message in thread if message.get("ts") == root_ts), item)
                await _append_slack_update(db, link, external_id, external_id, f"Slack thread {permalink}:\n{root.get('text', '')[:_MAX_TEXT]}")
            continue
        if len(references) > 1:
            await _record(db, "slack_thread", external_id, "needs_review", f"Multiple Jira references: {permalink}\n\n{transcript}"[:_MAX_TEXT])
            continue
        if not _looks_actionable(item.get("text", "")):
            await _record(db, "slack_thread", external_id, "needs_review", f"Slack thread: {permalink}\n\n{transcript}"[:_MAX_TEXT])
            continue
        title = re.sub(r"<@[^>]+>", "", item.get("text", "")).strip().splitlines()[0][:200]
        await _record(db, "slack_thread", external_id, "pending", permalink)
        issue = await jira.create_issue(settings.slack_jira_project_key, title or "Slack action item", f"Slack thread: {permalink}\n\n{transcript}")
        event = await _event(db, "slack_thread", external_id)
        event.detail = issue.get("key")
        await db.commit()
        full_issue = await jira.issue(issue["key"])
        link, created = await _ensure_issue_task(db, jira, full_issue)
        if link:
            for reply in thread:
                reply_ts = reply.get("ts")
                if reply_ts and reply_ts != root_ts and not await _event(db, "slack_reply_out", f"{channel}:{reply_ts}"):
                    db.add(IntegrationEvent(source="slack_reply_out", external_id=f"{channel}:{reply_ts}", status="processed", detail=event.detail))
            event.status = "processed"
            await db.commit()
            await _start_task_if_pending(db, link)
    # Follow every ticketed thread, including replies that no longer mention the user.
    ticketed = (await db.execute(select(IntegrationEvent).where(
        IntegrationEvent.source == "slack_thread", IntegrationEvent.status == "processed",
    ))).scalars().all()
    for event in ticketed:
        if not event.detail or not re.fullmatch(r"[A-Z][A-Z0-9_]*-\d+", event.detail):
            continue
        channel, root_ts = event.external_id.split(":", 1)
        link = (await db.execute(select(JiraIssueLink).where(JiraIssueLink.issue_key == event.detail))).scalar_one_or_none()
        linked_task = await db.get(Task, link.task_id) if link else None
        if linked_task:
            # Persisted delivery retries must survive the polling cursor and
            # include the root message as well as replies.
            async with task_sources.lock_for(linked_task.project_id):
                pending_updates = (await db.execute(select(TaskSourceEvent).where(
                    TaskSourceEvent.task_id == link.task_id,
                    TaskSourceEvent.status == "pending",
                ))).scalars().all()
                for pending_update in pending_updates:
                    await task_sources.dispatch_update(db, pending_update)
        for message in await slack.thread(channel, root_ts):
            ts = message.get("ts")
            if not ts or float(ts) <= since.timestamp() or float(ts) > until.timestamp():
                continue
            if message.get("user") == slack.user_id or ts == root_ts:
                continue
            reply_id = f"{channel}:{ts}"
            previous_reply = await _event(db, "slack_reply_out", reply_id)
            if previous_reply:
                # Retry task delivery after a failed resume without duplicating
                # a posted Jira comment or appending another conversation message.
                if link:
                    pending = (await db.execute(select(TaskSourceEvent).where(
                        TaskSourceEvent.task_id == link.task_id,
                        TaskSourceEvent.event_key == f"slack:{reply_id}",
                        TaskSourceEvent.status == "pending",
                    ))).scalar_one_or_none()
                    if pending:
                        await task_sources.dispatch_update(db, pending)
                continue
            content = message.get("text", "").strip()
            if not content:
                continue
            await _record(db, "slack_reply_out", reply_id, "pending", event.detail)
            posted = await jira.post_comment(event.detail, f"Slack thread reply by {message.get('user', 'unknown')}:\n{content[:_MAX_TEXT]}")
            await _record(db, "jira_comment_out", str(posted["id"]), "processed", event.detail)
            reply = await _event(db, "slack_reply_out", reply_id)
            reply.status = "processed"
            await db.commit()
            if link:
                await _append_slack_update(db, link, event.external_id, reply_id, f"Slack reply by {message.get('user', 'unknown')}:\n{content[:_MAX_TEXT]}")
    settings.slack_cursor = until
    await db.commit()


async def run_integration_once(*, client: httpx.AsyncClient | None = None) -> IntegrationRun | None:
    """Run one bounded scan. Separate cursors survive a partial source failure."""
    if _local_lock.locked():
        return None
    async with _local_lock:
        # Keep one dedicated connection for the advisory lock across DB commits.
        async with engine.connect() as lock_connection:
            postgres = lock_connection.dialect.name == "postgresql"
            if postgres and not (await lock_connection.execute(text("SELECT pg_try_advisory_lock(:id)"), {"id": _advisory_lock_id})).scalar():
                return None
            try:
                async with SessionLocal() as db:
                    settings = await db.get(IntegrationSettings, 1)
                    if not settings or not settings.enabled:
                        return None
                    run = IntegrationRun(status="running")
                    db.add(run)
                    settings.last_run_at = utcnow()
                    settings.last_status = "running"
                    await db.commit()
                    until = utcnow()
                    owns_client = client is None
                    http = client or httpx.AsyncClient(timeout=30)
                    errors: list[str] = []
                    try:
                        jira = JiraClient(settings, http)
                        try:
                            await _sync_jira(db, settings, jira, until)
                        except Exception as exc:
                            logger.exception("Jira integration scan failed")
                            errors.append(f"Jira: {exc}")
                            await db.rollback()
                            await db.refresh(settings)
                        if settings.slack_token:
                            try:
                                await _sync_slack(db, settings, SlackClient(settings, http), jira, until)
                            except Exception as exc:
                                logger.exception("Slack integration scan failed")
                                errors.append(f"Slack: {exc}")
                                await db.rollback()
                                await db.refresh(settings)
                    except Exception as exc:
                        logger.exception("Jira/Slack integration configuration failed")
                        errors.append(str(exc))
                        await db.rollback()
                    finally:
                        if owns_client:
                            await http.aclose()
                    if errors:
                        await db.refresh(settings)
                        await db.refresh(run)
                    run.status = "failed" if errors else "succeeded"
                    run.error = "; ".join(errors)[:1000] if errors else None
                    run.ended_at = utcnow()
                    settings.last_status = run.status
                    settings.last_error = run.error
                    await db.commit()
                    return run
            finally:
                if postgres:
                    await lock_connection.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": _advisory_lock_id})
