import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import AgentBackend, CronJob, Message, MessageSender, Project, Task, TaskStatus
from app.services import recurring_memory
from app.services.claude_plugins import mcp_names
from app.services.agent_backends.base import AdapterBindings
from app.services.agent_backends.claude_code import ClaudeCodeAdapter
from app.services.agent_backends.codex import CodexAdapter
from app.services.process_manager import ProcessManager


def install_plugin(home, name, config, **manifest):
    root = home / '.claude' / 'plugins' / 'cache' / name
    (root / '.claude-plugin').mkdir(parents=True)
    (root / '.claude-plugin' / 'plugin.json').write_text(json.dumps({'name': name, **manifest}))
    (root / '.mcp.json').write_text(json.dumps(config))
    registry_path = home / '.claude' / 'plugins' / 'installed_plugins.json'
    registry = json.loads(registry_path.read_text()) if registry_path.exists() else {'plugins': {}}
    registry['plugins'][f'{name}@marketplace'] = [{'scope': 'user', 'installPath': str(root)}]
    registry_path.write_text(json.dumps(registry))
    return root


def test_plugin_namespace_allow_rules_cover_live_slack_tool_and_respect_project_disable(tmp_path, monkeypatch):
    install_plugin(tmp_path, 'slack', {'mcpServers': {'slack': {'url': 'https://example.test/slack'}}})
    install_plugin(tmp_path, 'atlassian', {'atlassian': {'url': 'https://example.test/jira'}})
    install_plugin(tmp_path, 'disabled', {'nope': {'command': 'ignored'}}, defaultEnabled=False)
    install_plugin(tmp_path, 'inline', {}, mcpServers={'api': {'command': 'inline-mcp'}})
    assert mcp_names(None, tmp_path) == ('plugin_atlassian_atlassian', 'plugin_inline_api', 'plugin_slack_slack')
    import app.services.claude_plugins as plugins
    monkeypatch.setattr(plugins.Path, 'home', lambda: tmp_path)
    bindings = AdapterBindings(primary_directory=str(tmp_path), directories=[str(tmp_path)], mcp_servers={},
        tool_rules=[{'decision': 'deny', 'backend': 'claude_code', 'claude_pattern': 'mcp__plugin_slack_slack__slack_send_message'}],
        agent_profiles={}, skills={}, recurring_memory_directory=str(tmp_path / 'memory'))
    task = SimpleNamespace(cron_job_id=uuid.uuid4(), initial_prompt='Check Slack', model='haiku', fallback_models=[], thinking_level=None)
    flags = ClaudeCodeAdapter().build_interactive_command(task, SimpleNamespace(default_model=None), bindings, {}).argv
    allowed = flags[flags.index('--allowedTools') + 1].split(',')
    actual_tool = 'mcp__plugin_slack_slack__slack_search_public_and_private'
    assert any(actual_tool.startswith(rule.removesuffix('*')) for rule in allowed)
    assert f'Write(/{tmp_path}/memory/**)' in allowed
    assert 'mcp__plugin_slack_slack__slack_send_message' in flags[flags.index('--disallowedTools') + 1]
    settings_path = tmp_path / '.claude' / 'settings.local.json'
    settings_path.write_text(json.dumps({'enabledPlugins': {'slack@marketplace': False}}))
    assert 'plugin_slack_slack' not in mcp_names(str(tmp_path), tmp_path)
    (tmp_path / '.claude' / 'plugins' / 'installed_plugins.json').write_text('{broken')
    assert mcp_names(str(tmp_path), tmp_path) == ()


@pytest.mark.asyncio
async def test_memory_survives_new_runs_and_job_edits_and_is_isolated(db_engine, tmp_path, monkeypatch):
    monkeypatch.setattr(recurring_memory.settings, 'data_dir', tmp_path)
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as db:
        project = Project(name='Work', default_backend=AgentBackend.claude_code)
        db.add(project)
        await db.flush()
        job = CronJob(project_id=project.id, name='Slack triage', schedule_expr='0 * * * *', prompt='Check Slack', backend=AgentBackend.claude_code)
        other = CronJob(project_id=project.id, name='Other', schedule_expr='0 * * * *', prompt='Other', backend=AgentBackend.codex)
        db.add_all([job, other])
        await db.flush()
        old = Task(project_id=project.id, cron_job_id=job.id, title='run', initial_prompt='work', backend=AgentBackend.claude_code, status=TaskStatus.waiting_on_you)
        db.add(old)
        await db.flush()
        db.add(Message(task_id=old.id, sender=MessageSender.agent, content_text='Mapped APP-1 to task 123; processed C1:100'))
        await db.commit()
        root = await recurring_memory.refresh(db, job.id)
        assert 'Mapped APP-1' in (root / 'MEMORY.md').read_text()
        notes = root / 'NOTES.md'
        notes.write_text('jira:APP-1 = task 123; last Slack reply C1:100')
        job.name = 'Renamed agent'
        new = Task(project_id=project.id, cron_job_id=job.id, title='next', initial_prompt='work', backend=AgentBackend.codex, status=TaskStatus.running)
        db.add(new)
        await db.commit()
        assert await recurring_memory.refresh(db, job.id) == root
        assert notes.read_text() == 'jira:APP-1 = task 123; last Slack reply C1:100'
        assert 'Renamed agent' in (root / 'MEMORY.md').read_text()
        assert str(new.id) in (root / 'MEMORY.md').read_text()
        other_root = await recurring_memory.refresh(db, other.id)
        assert other_root != root and 'APP-1' not in (other_root / 'MEMORY.md').read_text()
        assert root.stat().st_mode & 0o777 == 0o700
        assert (root / 'MEMORY.md').stat().st_mode & 0o777 == 0o600
        assert str(notes) in recurring_memory.guidance(job.id)
        loaded = await ProcessManager()._load_project(db, project.id)
        bindings = await ProcessManager()._bindings_for(db, loaded, new)
        assert bindings.recurring_memory_directory == str(root)
        assert str(root) in bindings.directories
        codex = CodexAdapter().build_command(new, loaded, bindings, {})
        assert str(root / 'NOTES.md') in codex.stdin_payload
        assert str(root) in codex.argv
        old_bindings = await ProcessManager()._bindings_for(db, loaded, old)
        claude = ClaudeCodeAdapter().resume_command(old, loaded, old_bindings, {}, 'session', 'Continue')
        assert str(root / 'NOTES.md') in claude.argv[claude.argv.index('--append-system-prompt') + 1]
        import app.services.process_manager as pm
        monkeypatch.setattr(pm, 'SessionLocal', factory)
        monkeypatch.setattr(pm, 'broadcast', AsyncMock())
        await ProcessManager()._set_status(new.id, TaskStatus.failed, completed=True)
        assert 'Status: failed' in (root / 'MEMORY.md').read_text()
        assert notes.read_text().startswith('jira:APP-1')
        monkeypatch.setattr(recurring_memory, 'refresh', AsyncMock(side_effect=OSError('disk full')))
        await recurring_memory.refresh_after_status(db, new)
