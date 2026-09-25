"""Coverage for deterministic support services and runtime dispatch."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings, settings
from app.core import security
from app.db.models import AgentBackend, CronJob, Message, MessageSender, Project, RuntimeMode, Task
from app.services import context_compression, cron_scheduler, model_catalog, retry
from app.services.agent_backends.base import AgentText
from app.services.runtime_manager import RuntimeManager


def test_settings_paths_database_url_and_directories(tmp_path):
    configured = Settings(
        postgres_host="db",
        postgres_port=5433,
        postgres_user="user",
        postgres_password="pass",
        postgres_db="name",
        data_dir=tmp_path / "data",
        secret_key_file=tmp_path / "keys" / "secret.key",
        terminal_allowed_origins=" http://one ,, http://two ",
    )
    assert configured.database_url == "postgresql+psycopg://user:pass@db:5433/name"
    assert configured.terminal_allowed_origin_set == {"http://one", "http://two"}
    assert configured.transcripts_dir == tmp_path / "data" / "transcripts"
    assert configured.media_dir == tmp_path / "data" / "media"
    assert configured.backend_sessions_dir == tmp_path / "data" / "backend-sessions"
    assert configured.terminals_dir == tmp_path / "data" / "terminals"
    configured.ensure_dirs()
    assert all(path.is_dir() for path in (
        configured.data_dir,
        configured.transcripts_dir,
        configured.media_dir,
        configured.backend_sessions_dir,
        configured.terminals_dir,
        configured.secret_key_file.parent,
    ))


def test_security_creates_loads_and_uses_key(tmp_path, monkeypatch):
    key_file = tmp_path / "secret.key"
    monkeypatch.setattr(settings, "secret_key_file", key_file)
    monkeypatch.setattr(type(settings), "ensure_dirs", lambda self: key_file.parent.mkdir(parents=True, exist_ok=True))
    generated = security._load_or_create_key()
    assert key_file.read_bytes() == generated
    assert security._load_or_create_key() == generated
    monkeypatch.setattr(security, "_fernet", Fernet(generated))
    encrypted = security.encrypt_secret("value")
    assert encrypted != b"value"
    assert security.decrypt_secret(encrypted) == "value"


@pytest.mark.parametrize(
    "message, expected",
    [
        ("usage limit reached", "transient"),
        ("RATE LIMIT", "transient"),
        ("HTTP 429", "transient"),
        ("ECONNRESET", "transient"),
        ("request timeout", "transient"),
        ("getaddrinfo failed", "transient"),
        ("network unreachable", "transient"),
        ("bad prompt", "other"),
        (None, "other"),
    ],
)
def test_retry_classification(message, expected):
    assert retry.classify(1, message).value == expected


def test_retry_backoff_is_exponential_and_capped(monkeypatch):
    monkeypatch.setattr(settings, "retry_base_seconds", 3)
    monkeypatch.setattr(settings, "retry_max_seconds", 10)
    assert retry.compute_backoff(0) == 3
    assert retry.compute_backoff(1) == 6
    assert retry.compute_backoff(4) == 10


@pytest.mark.asyncio
async def test_runtime_manager_routes_every_operation(monkeypatch):
    structured = SimpleNamespace(**{name: AsyncMock() for name in (
        "trigger", "resume", "cancel", "complete", "retry_now", "restart_from_beginning",
        "switch_backend", "resume_after_approval", "reconcile_interrupted_tasks", "shutdown",
    )})
    structured.reconcile_interrupted_tasks.return_value = 2
    structured.diagnostic = "available"
    terminal = SimpleNamespace(**{name: AsyncMock() for name in (
        "trigger", "resume", "cancel", "complete", "retry_now", "restart_from_beginning", "switch_backend", "shutdown",
    )})
    manager = RuntimeManager(structured, terminal)
    task_id = uuid.uuid4()

    monkeypatch.setattr(manager, "_mode", AsyncMock(return_value=RuntimeMode.structured))
    await manager.trigger(task_id)
    await manager.resume(task_id)
    await manager.cancel(task_id)
    await manager.complete(task_id)
    await manager.retry_now(task_id)
    await manager.restart_from_beginning(task_id)
    await manager.switch_backend(task_id, AgentBackend.codex)
    for name in ("trigger", "resume", "cancel", "complete", "retry_now", "restart_from_beginning", "switch_backend"):
        assert getattr(structured, name).await_count == 1

    monkeypatch.setattr(manager, "_mode", AsyncMock(return_value=RuntimeMode.interactive))
    monkeypatch.setattr(settings, "interactive_terminal_enabled", True)
    await manager.trigger(task_id)
    await manager.resume(task_id)
    await manager.cancel(task_id)
    await manager.complete(task_id)
    await manager.retry_now(task_id)
    await manager.restart_from_beginning(task_id)
    await manager.switch_backend(task_id, AgentBackend.claude_code)
    for name in ("trigger", "resume", "cancel", "complete", "retry_now", "restart_from_beginning", "switch_backend"):
        assert getattr(terminal, name).await_count == 1

    monkeypatch.setattr(settings, "interactive_terminal_enabled", False)
    with pytest.raises(RuntimeError, match="disabled"):
        await manager.trigger(task_id)
    await manager.resume_after_approval(task_id)
    assert await manager.reconcile_interrupted_tasks() == 2
    await manager.shutdown()
    structured.shutdown.assert_awaited_once()
    terminal.shutdown.assert_awaited_once()
    assert manager.diagnostic == "available"


@pytest.mark.asyncio
async def test_runtime_manager_reads_modes_from_database(db_engine, monkeypatch):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr("app.services.runtime_manager.SessionLocal", session_factory)
    project = Project(name="P", default_backend=AgentBackend.codex)
    async with session_factory() as db:
        db.add(project)
        await db.flush()
        task = Task(project_id=project.id, title="T", initial_prompt="go", backend=AgentBackend.codex, runtime_mode=RuntimeMode.interactive)
        db.add(task)
        await db.commit()
        task_id = task.id
    manager = RuntimeManager(Mock(), Mock())
    assert await manager._mode(task_id) == RuntimeMode.interactive
    assert await manager._mode(uuid.uuid4()) == RuntimeMode.structured


def test_model_discovery_reads_env_and_local_files(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    (codex_dir / "models_cache.json").write_text(json.dumps({"models": [
        {"slug": "visible", "visibility": "list"},
        {"slug": "hidden", "visibility": "hidden"},
        "bad",
    ]}))
    (codex_dir / "config.toml").write_text('model = "configured"\n')
    monkeypatch.setenv("MUSTER_CODEX_MODELS", "env-one, visible")
    names, error = model_catalog._discover(AgentBackend.codex)
    assert {"env-one", "visible", "configured", *model_catalog._DEFAULTS[AgentBackend.codex]} <= set(names)
    assert "hidden" not in names
    assert error is None

    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(json.dumps({"model": "claude-local"}))
    names, error = model_catalog._discover(AgentBackend.claude_code)
    assert "claude-local" in names
    assert error is None
    assert model_catalog._label("gpt_test-model") == "Gpt Test Model"


def test_model_discovery_reports_invalid_local_config(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    path = tmp_path / ".claude"
    path.mkdir()
    (path / "settings.json").write_text("{")
    names, error = model_catalog._discover(AgentBackend.claude_code)
    assert model_catalog._DEFAULTS[AgentBackend.claude_code][0] in names
    assert error


@pytest.mark.asyncio
async def test_model_catalog_cache_and_force(monkeypatch):
    model_catalog._cache.clear()
    discover = Mock(return_value=(["model-a"], None))
    monkeypatch.setattr(model_catalog, "_discover", discover)
    first = await model_catalog.get_catalog(AgentBackend.codex)
    second = await model_catalog.get_catalog(AgentBackend.codex)
    forced = await model_catalog.get_catalog(AgentBackend.codex, force=True)
    assert first["cached"] is False
    assert second["cached"] is True
    assert forced["cached"] is False
    assert discover.call_count == 2
    assert first["items"][0]["label"] == "Model A"

    stale = model_catalog._cache[AgentBackend.codex]
    stale.refreshed_at = datetime.now(timezone.utc) - timedelta(hours=2)
    refreshed = await model_catalog.get_catalog(AgentBackend.codex)
    assert refreshed["cached"] is False


def test_context_commands_and_message_format(monkeypatch):
    monkeypatch.setattr(settings, "claude_code_bin", "claude-test")
    monkeypatch.setattr(settings, "codex_bin", "codex-test")
    claude = context_compression._summarize_command(AgentBackend.claude_code, "prompt")
    codex = context_compression._summarize_command(AgentBackend.codex, "prompt")
    assert claude.argv == ["claude-test", "-p", "prompt", "--output-format", "stream-json"]
    assert codex.argv == ["codex-test", "exec", "-", "--json"]
    assert codex.stdin_payload == "prompt"
    message = SimpleNamespace(sender=MessageSender.agent, content_text=None)
    assert context_compression._format_message(message) == "[agent] "


@pytest.mark.asyncio
async def test_context_one_shot_collects_only_agent_text(monkeypatch):
    class Stdin:
        def __init__(self):
            self.written = b""
            self.closed = False
        def write(self, value): self.written += value
        def close(self): self.closed = True

    class Stdout:
        def __aiter__(self):
            self.lines = iter([b"one\n", b"ignore\n", b"two\n"])
            return self
        async def __anext__(self):
            try: return next(self.lines)
            except StopIteration: raise StopAsyncIteration

    process = SimpleNamespace(stdin=Stdin(), stdout=Stdout(), wait=AsyncMock())
    monkeypatch.setattr(context_compression.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    adapter = SimpleNamespace(parse_line=lambda line: AgentText(line.strip()) if line.strip() != "ignore" else None)
    monkeypatch.setitem(context_compression._ADAPTERS, AgentBackend.codex, adapter)
    result = await context_compression._run_one_shot(AgentBackend.codex, "summarize")
    assert result == "onetwo"
    assert process.stdin.written == b"summarize"
    assert process.stdin.closed is True
    process.wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_context_one_shot_tolerates_closed_stdin_and_empty_summary(monkeypatch):
    class BrokenStdin:
        def write(self, value):
            raise BrokenPipeError
        def close(self):
            pass

    class EmptyStdout:
        def __aiter__(self):
            return self
        async def __anext__(self):
            raise StopAsyncIteration

    process = SimpleNamespace(stdin=BrokenStdin(), stdout=EmptyStdout(), wait=AsyncMock())
    monkeypatch.setattr(context_compression.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    assert await context_compression._run_one_shot(AgentBackend.codex, "prompt") == ""


@pytest.mark.asyncio
async def test_context_compress_handles_missing_short_and_long_threads(db_engine, monkeypatch, tmp_path):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(context_compression, "SessionLocal", session_factory)
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    with pytest.raises(ValueError, match="unknown task"):
        await context_compression.compress(uuid.uuid4())

    async with session_factory() as db:
        project = Project(name="P", default_backend=AgentBackend.codex)
        db.add(project)
        await db.flush()
        task = Task(project_id=project.id, title="T", initial_prompt="go", backend=AgentBackend.codex)
        db.add(task)
        await db.flush()
        task_id = task.id
        db.add_all([Message(task_id=task_id, sender=MessageSender.user, content_text=str(index)) for index in range(12)])
        await db.commit()

    run = AsyncMock(return_value="summary")
    monkeypatch.setattr(context_compression, "_run_one_shot", run)
    snapshot = await context_compression.compress(task_id)
    assert snapshot.summary_text == "summary"
    run.assert_awaited_once()

    async with session_factory() as db:
        empty = Task(project_id=project.id, title="Empty", initial_prompt="go", backend=AgentBackend.codex)
        db.add(empty)
        await db.commit()
        empty_id = empty.id
    snapshot = await context_compression.compress(empty_id)
    assert snapshot.summary_text == "(nothing to summarize yet)"

    async with session_factory() as db:
        fallback = Task(project_id=project.id, title="Fallback", initial_prompt="go", backend=AgentBackend.codex)
        db.add(fallback)
        await db.flush()
        fallback_id = fallback.id
        db.add_all([Message(task_id=fallback_id, sender=MessageSender.user, content_text=str(index)) for index in range(11)])
        await db.commit()
    run.return_value = ""
    snapshot = await context_compression.compress(fallback_id)
    assert snapshot.summary_text.startswith("[1 earlier messages")


def test_cron_validation_handles_valid_invalid_and_parser_error(monkeypatch):
    assert cron_scheduler.is_valid_cron("0 9 * * *") is True
    assert cron_scheduler.is_valid_cron("not cron") is False
    monkeypatch.setattr(cron_scheduler.croniter, "is_valid", Mock(side_effect=RuntimeError("bad")))
    assert cron_scheduler.is_valid_cron("anything") is False


def test_cron_sync_replaces_jobs_and_skips_invalid_entries(monkeypatch):
    existing = [SimpleNamespace(id="cron_job:old"), SimpleNamespace(id="unrelated")]
    scheduler = SimpleNamespace(
        get_jobs=Mock(return_value=existing),
        remove_job=Mock(),
        add_job=Mock(),
    )
    rows = [
        SimpleNamespace(id=uuid.uuid4(), name="invalid", schedule_expr="bad"),
        SimpleNamespace(id=uuid.uuid4(), name="valid", schedule_expr="0 9 * * *"),
    ]

    class Result:
        def scalars(self): return self
        def all(self): return rows

    class FakeSession:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, statement): return Result()

    monkeypatch.setattr(cron_scheduler, "scheduler", scheduler)
    monkeypatch.setattr(cron_scheduler, "Session", lambda engine: FakeSession())
    monkeypatch.setattr(cron_scheduler, "is_valid_cron", lambda expr: expr != "bad")
    trigger = object()
    monkeypatch.setattr(cron_scheduler.CronTrigger, "from_crontab", Mock(return_value=trigger))
    cron_scheduler.sync_jobs_from_db()
    scheduler.remove_job.assert_called_once_with("cron_job:old")
    scheduler.add_job.assert_called_once()

    monkeypatch.setattr(cron_scheduler, "is_valid_cron", lambda expr: True)
    monkeypatch.setattr(cron_scheduler.CronTrigger, "from_crontab", Mock(side_effect=ValueError("bad")))
    scheduler.add_job.reset_mock()
    cron_scheduler.sync_jobs_from_db()
    scheduler.add_job.assert_not_called()


@pytest.mark.asyncio
async def test_cron_fire_creates_structured_task(db_engine, monkeypatch):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(cron_scheduler, "SessionLocal", session_factory)
    trigger = AsyncMock()
    monkeypatch.setattr(cron_scheduler.process_manager, "trigger", trigger)
    async with session_factory() as db:
        project = Project(name="P", default_backend=AgentBackend.codex)
        db.add(project)
        await db.flush()
        enabled = CronJob(
            project_id=project.id,
            name="daily",
            schedule_expr="0 9 * * *",
            prompt="report",
            backend=AgentBackend.codex,
            enabled=True,
        )
        disabled = CronJob(
            project_id=project.id,
            name="off",
            schedule_expr="0 9 * * *",
            prompt="skip",
            backend=AgentBackend.codex,
            enabled=False,
        )
        db.add_all([enabled, disabled])
        await db.commit()
        enabled_id, disabled_id = enabled.id, disabled.id

    await cron_scheduler._fire_cron_job(uuid.uuid4())
    await cron_scheduler._fire_cron_job(disabled_id)
    trigger.assert_not_awaited()
    await cron_scheduler._fire_cron_job(enabled_id)
    trigger.assert_awaited_once()
    async with session_factory() as db:
        loaded = await db.get(CronJob, enabled_id)
        assert loaded.last_status == "triggered"
