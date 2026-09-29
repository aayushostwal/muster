"""Configuration, mappings, and run status for Jira/Slack automation."""
from __future__ import annotations

import re
import uuid
from ipaddress import ip_address
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import encrypt_secret
from app.db.models import IntegrationEvent, IntegrationRun, IntegrationSettings, JiraProjectMapping, Project
from app.db.session import get_db
from app.services.cron_scheduler import is_valid_cron, sync_jobs_from_db
from app.services.integrations import JiraClient, RemoteError, _ensure_issue_task, _start_task_if_pending, run_integration_once

def _require_local(request: Request) -> None:
    host = request.client.host if request.client else ""
    try:
        local = ip_address(host).is_loopback
    except ValueError:
        local = False
    origin = request.headers.get("origin")
    origin_host = urlparse(origin).hostname if origin else None
    if not local or (origin and origin_host not in {"localhost", "127.0.0.1", "::1"}):
        raise HTTPException(403, "Integration settings require a local client")


router = APIRouter(prefix="/integrations", tags=["integrations"], dependencies=[Depends(_require_local)])


class IntegrationConfigUpdate(BaseModel):
    enabled: bool | None = None
    schedule_expr: str | None = None
    timezone: str | None = None
    jira_base_url: str | None = None
    jira_email: str | None = None
    jira_token: str | None = None
    slack_token: str | None = None
    slack_user_id: str | None = None
    slack_jira_project_key: str | None = None


class MappingCreate(BaseModel):
    jira_project_key: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,29}$")
    project_id: uuid.UUID


class MappingRead(MappingCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


class ExistingIssueLink(BaseModel):
    issue_key: str = Field(pattern=r"^[A-Z][A-Z0-9_]*-\d+$")


async def _settings(db: AsyncSession) -> IntegrationSettings:
    row = await db.get(IntegrationSettings, 1)
    if row is None:
        row = IntegrationSettings(id=1)
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


def _read(row: IntegrationSettings) -> dict:
    return {
        "enabled": row.enabled, "schedule_expr": row.schedule_expr, "timezone": row.timezone,
        "jira_base_url": row.jira_base_url, "jira_email": row.jira_email,
        "has_jira_token": bool(row.jira_token), "has_slack_token": bool(row.slack_token),
        "slack_user_id": row.slack_user_id,
        "slack_jira_project_key": row.slack_jira_project_key,
        "jira_cursor": row.jira_cursor, "slack_cursor": row.slack_cursor,
        "last_run_at": row.last_run_at, "last_status": row.last_status,
        "last_error": row.last_error,
    }


@router.get("/config")
async def get_config(db: AsyncSession = Depends(get_db)):
    return _read(await _settings(db))


@router.patch("/config")
async def update_config(body: IntegrationConfigUpdate, db: AsyncSession = Depends(get_db)):
    row = await _settings(db)
    changes = body.model_dump(exclude_unset=True)
    if "schedule_expr" in changes and (not changes["schedule_expr"] or len(changes["schedule_expr"].split()) != 5 or not is_valid_cron(changes["schedule_expr"])):
        raise HTTPException(422, "Enter a valid five-field cron expression")
    if "timezone" in changes:
        try:
            ZoneInfo(changes["timezone"])
        except (ZoneInfoNotFoundError, TypeError, ValueError) as exc:
            raise HTTPException(422, "Enter a valid IANA timezone") from exc
    if "jira_base_url" in changes and changes["jira_base_url"] and not changes["jira_base_url"].startswith("https://"):
        raise HTTPException(422, "Jira URL must use HTTPS")
    for key in ("jira_token", "slack_token"):
        if key in changes:
            value = changes.pop(key)
            setattr(row, key, encrypt_secret(value) if value else None)
    for key, value in changes.items():
        setattr(row, key, value)
    if row.enabled and not (row.jira_base_url and row.jira_email and row.jira_token):
        raise HTTPException(422, "Set Jira URL, email, and token before enabling")
    await db.commit()
    await db.refresh(row)
    sync_jobs_from_db()
    return _read(row)


@router.get("/mappings")
async def list_mappings(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(JiraProjectMapping).order_by(JiraProjectMapping.jira_project_key))).scalars().all()
    return {"items": [MappingRead.model_validate(row) for row in rows]}


@router.post("/mappings", status_code=201, response_model=MappingRead)
async def create_mapping(body: MappingCreate, db: AsyncSession = Depends(get_db)):
    if await db.get(Project, body.project_id) is None:
        raise HTTPException(404, "Muster project not found")
    existing = (await db.execute(select(JiraProjectMapping).where(JiraProjectMapping.jira_project_key == body.jira_project_key))).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "Jira project key is already mapped")
    row = JiraProjectMapping(**body.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/mappings/{mapping_id}", status_code=204)
async def delete_mapping(mapping_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    row = await db.get(JiraProjectMapping, mapping_id)
    if row is None:
        raise HTTPException(404, "Mapping not found")
    await db.delete(row)
    await db.commit()


@router.post("/run-now")
async def run_now():
    run = await run_integration_once()
    if run is None:
        raise HTTPException(409, "Integration is disabled or a scan is already running")
    return {"id": run.id, "status": run.status, "error": run.error}


@router.get("/runs")
async def list_runs(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(IntegrationRun).order_by(IntegrationRun.started_at.desc()).limit(20))).scalars().all()
    return {"items": [{"id": row.id, "started_at": row.started_at, "ended_at": row.ended_at,
                       "status": row.status, "error": row.error} for row in rows]}


@router.get("/review")
async def list_review(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(IntegrationEvent).where(IntegrationEvent.status.in_(["needs_review", "pending"])).order_by(IntegrationEvent.created_at.desc()).limit(100))).scalars().all()
    return {"items": [{"id": row.id, "source": row.source, "status": row.status, "external_id": row.external_id,
                       "detail": row.detail, "created_at": row.created_at} for row in rows]}


@router.post("/review/{event_id}/create-ticket")
async def create_review_ticket(event_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    event = await db.get(IntegrationEvent, event_id)
    if event is None or event.source != "slack_thread" or event.status not in {"needs_review", "pending"}:
        raise HTTPException(404, "Slack review item not found")
    if event.status == "pending" and not re.fullmatch(r"[A-Z][A-Z0-9_]*-\d+", event.detail or ""):
        raise HTTPException(409, "Ticket creation outcome is unknown. Check Jira and link the existing issue key.")
    settings = await _settings(db)
    if not settings.slack_jira_project_key:
        raise HTTPException(422, "Choose a Jira project for Slack tickets")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            jira = JiraClient(settings, client)
            if event.status == "needs_review":
                description = event.detail or "Slack action item"
                title = description.splitlines()[-1].split(":", 1)[-1].strip()[:200] or "Slack action item"
                event.status = "pending"
                await db.commit()
                issue = await jira.create_issue(settings.slack_jira_project_key, title, description)
                event.detail = issue["key"]
                await db.commit()
            issue = await jira.issue(event.detail)
            link, created = await _ensure_issue_task(db, jira, issue)
            if link:
                event.status = "processed"
                await db.commit()
                await _start_task_if_pending(db, link)
                return {"issue_key": link.issue_key, "task_id": link.task_id}
            raise HTTPException(422, "Map this Jira project to a Muster project first")
    except (httpx.HTTPError, RemoteError) as exc:
        raise HTTPException(502, "Remote API request failed") from exc


@router.post("/review/{event_id}/link-ticket")
async def link_review_ticket(event_id: uuid.UUID, body: ExistingIssueLink, db: AsyncSession = Depends(get_db)):
    event = await db.get(IntegrationEvent, event_id)
    if event is None or event.source != "slack_thread" or event.status not in {"needs_review", "pending"}:
        raise HTTPException(404, "Slack review item not found")
    settings = await _settings(db)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            jira = JiraClient(settings, client)
            issue = await jira.issue(body.issue_key)
            link, created = await _ensure_issue_task(db, jira, issue)
            if link is None:
                raise HTTPException(422, "Map this Jira project to a Muster project first")
            event.detail = link.issue_key
            event.status = "processed"
            await db.commit()
            await _start_task_if_pending(db, link)
            return {"issue_key": link.issue_key, "task_id": link.task_id}
    except (httpx.HTTPError, RemoteError) as exc:
        raise HTTPException(502, "Remote API request failed") from exc


@router.post("/review/{event_id}/dismiss")
async def dismiss_review(event_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    event = await db.get(IntegrationEvent, event_id)
    if event is None or event.status != "needs_review":
        raise HTTPException(404, "Review item not found")
    event.status = "dismissed"
    await db.commit()
    return {"status": "dismissed"}
