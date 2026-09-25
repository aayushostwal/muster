from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import AgentBackend, Project, Task, TaskBackendSession, TaskStatus
from app.services.process_manager import (
    _get_or_create_backend_session,
    _resolve_backend_session_path,
)


@pytest.mark.asyncio
async def test_backend_session_persists_resume_handle_and_storage_path(db_engine, monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.process_manager.settings.data_dir", tmp_path / "muster-data")
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)

    async with session_local() as db:
        project = Project(name="Muster", default_backend=AgentBackend.codex)
        db.add(project)
        await db.flush()
        task = Task(
            project_id=project.id,
            title="Persistent session",
            initial_prompt="Continue later",
            status=TaskStatus.queued,
            backend=AgentBackend.codex,
            session_id="thread-123",
        )
        db.add(task)
        await db.flush()
        backend_session = await _get_or_create_backend_session(db, task)
        await db.commit()
        task_id = task.id

    async with session_local() as db:
        stored = await db.get(TaskBackendSession, backend_session.id)

    assert stored is not None
    assert stored.task_id == task_id
    assert stored.session_id == "thread-123"
    assert stored.storage_path == f"backend-sessions/{task_id}/codex"
    assert _resolve_backend_session_path(stored.storage_path) == (
        tmp_path / "muster-data" / stored.storage_path
    ).resolve()


@pytest.mark.asyncio
async def test_backend_session_storage_cannot_escape_muster_data(monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.process_manager.settings.data_dir", tmp_path / "muster-data")

    try:
        _resolve_backend_session_path("../../outside")
    except RuntimeError as exc:
        assert "escaped MUSTER_DATA_DIR" in str(exc)
    else:
        raise AssertionError("unsafe backend session path was accepted")
