"""In-process cron scheduling for CronJob rows.

See docs/SPEC.md "Integration seams" -> cron_scheduler.py.

`sync_jobs_from_db()` is intentionally a *synchronous* function -- its
signature is part of the frozen integration contract, called inline (no
`await`) from CronJob CRUD routes right after they commit. Since
app.db.session only wires up an async engine, this module opens its own
plain blocking SQLAlchemy engine against the same Postgres DSN: psycopg3
supports both sync and async use from the same "postgresql+psycopg" URL
(sync via `create_engine`, async via `create_async_engine`), so this is just
a second, synchronous entry point onto the same database. The alternative --
wrapping the async session in `asyncio.run()` -- would raise
"already running event loop" when called from inside an async FastAPI route
handler, which is the common case here.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from croniter import croniter
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import CronJob, IntegrationSettings, RuntimeMode, Task, TaskStatus
from app.db.session import SessionLocal
from app.services.process_manager import process_manager

logger = logging.getLogger(__name__)

# Started/stopped from app.main's lifespan.
scheduler = AsyncIOScheduler()

# Dedicated synchronous engine, used only by this module's sync DB callback.
_sync_engine = create_engine(settings.database_url, echo=False)

_JOB_ID_PREFIX = "cron_job:"


def is_valid_cron(expr: str) -> bool:
    """Validate a standard 5-field cron expression via croniter."""
    try:
        return croniter.is_valid(expr)
    except Exception:  # noqa: BLE001 - any parsing error means invalid
        return False


def sync_jobs_from_db() -> None:
    """Reschedule every enabled CronJob from Postgres into the in-memory
    AsyncIOScheduler. Call on startup and after any CronJob CRUD."""
    for job in scheduler.get_jobs():
        if job.id.startswith(_JOB_ID_PREFIX):
            scheduler.remove_job(job.id)

    with Session(_sync_engine) as db:
        rows = db.execute(select(CronJob).where(CronJob.enabled.is_(True))).scalars().all()
        integration = db.get(IntegrationSettings, 1)

    for cron_job in rows:
        if not is_valid_cron(cron_job.schedule_expr):
            logger.warning(
                "skipping cron job %s (%s): invalid schedule %r",
                cron_job.id, cron_job.name, cron_job.schedule_expr,
            )
            continue
        try:
            trigger = CronTrigger.from_crontab(cron_job.schedule_expr)
        except ValueError:
            logger.warning(
                "skipping cron job %s (%s): unparseable schedule %r",
                cron_job.id, cron_job.name, cron_job.schedule_expr,
            )
            continue
        scheduler.add_job(
            _fire_cron_job,
            trigger=trigger,
            id=f"{_JOB_ID_PREFIX}{cron_job.id}",
            args=[cron_job.id],
            replace_existing=True,
            misfire_grace_time=60,
        )
    if integration and integration.enabled:
        try:
            trigger = CronTrigger.from_crontab(integration.schedule_expr, timezone=ZoneInfo(integration.timezone))
            scheduler.add_job(_fire_integrations, trigger=trigger, id=f"{_JOB_ID_PREFIX}integrations",
                              replace_existing=True, max_instances=1, coalesce=True, misfire_grace_time=3600)
        except (ValueError, ZoneInfoNotFoundError):
            logger.warning("skipping invalid Jira/Slack integration schedule")


async def _fire_integrations() -> None:
    from app.services.integrations import run_integration_once

    await run_integration_once()


async def _fire_cron_job(cron_job_id: uuid.UUID) -> None:
    """Create a Task for this firing and hand it to the process manager --
    identical to the manual task-creation path (see docs/SPEC.md)."""
    async with SessionLocal() as db:
        cron_job = await db.get(CronJob, cron_job_id)
        if cron_job is None or not cron_job.enabled:
            return
        task = Task(
            project_id=cron_job.project_id,
            title=f"[cron] {cron_job.name}",
            initial_prompt=cron_job.prompt,
            backend=cron_job.backend,
            model=cron_job.model,
            status=TaskStatus.queued,
            runtime_mode=RuntimeMode.structured,
            cron_job_id=cron_job.id,
        )
        db.add(task)
        cron_job.last_run_at = datetime.now(timezone.utc)
        cron_job.last_status = "triggered"
        await db.commit()
        await db.refresh(task)
        task_id = task.id

    await process_manager.trigger(task_id)
