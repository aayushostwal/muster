"""Contract tests for the structured CLI event streams shown in the activity UI."""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

from app.services.agent_backends.base import (
    AdapterBindings,
    ActivityEvent,
    AgentText,
    SessionId,
    UsageEvent,
)
from app.services.agent_backends.claude_code import ClaudeCodeAdapter
from app.services.agent_backends.codex import CodexAdapter
from app.services.agent_backends.codex import create_codex_home_overlay
from app.services.agent_backends.codex import repair_codex_rollout_path
from app.db.models import AgentBackend


def test_codex_parses_session_activity_and_usage():
    adapter = CodexAdapter()

    session = adapter.parse_line(json.dumps({"type": "thread.started", "thread_id": "thread-123"}))
    assert session == SessionId("thread-123")

    activity = adapter.parse_line(
        json.dumps(
            {
                "type": "item.completed",
                "item": {"id": "item-1", "type": "file_change", "diff": "+new line"},
            }
        )
    )
    assert isinstance(activity, ActivityEvent)
    assert activity.kind == "diff"

    result = adapter.parse_line(
        json.dumps(
            {
                "type": "turn.completed",
                "usage": {"input_tokens": 12, "output_tokens": 7, "cached_input_tokens": 3},
            }
        )
    )
    assert isinstance(result, list)
    assert result[0] == UsageEvent(input_tokens=12, output_tokens=7, cached_tokens=3)

    denied_command = adapter.parse_line(
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "item-2",
                    "type": "command_execution",
                    "status": "failed",
                    "command": "git push",
                    "output": "This command requires approval",
                },
            }
        )
    )
    assert isinstance(denied_command, ActivityEvent)
    assert denied_command.metadata["is_error"] is True


def test_claude_parses_text_tool_calls_and_usage():
    adapter = ClaudeCodeAdapter()
    events = adapter.parse_line(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "Implemented the change."},
                        {"type": "tool_use", "id": "tool-1", "name": "Bash", "input": {"command": "npm test"}},
                    ]
                },
            }
        )
    )
    assert isinstance(events, list)
    assert isinstance(events[0], AgentText)
    assert isinstance(events[1], ActivityEvent)
    assert events[1].kind == "tool_call"

    result = adapter.parse_line(
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "usage": {"input_tokens": 20, "output_tokens": 10, "cache_read_input_tokens": 5},
            }
        )
    )
    assert isinstance(result, list)
    assert result[0] == UsageEvent(input_tokens=20, output_tokens=10, cached_tokens=5)

    tool_result = adapter.parse_line(
        json.dumps(
            {
                "type": "user",
                "session_id": "claude-session",
                "message": {
                    "content": [
                        {"type": "tool_result", "tool_use_id": "tool-1", "content": "tests passed"}
                    ]
                },
            }
        )
    )
    assert isinstance(tool_result, list)
    assert tool_result[0] == SessionId("claude-session")
    assert isinstance(tool_result[1], ActivityEvent)
    assert tool_result[1].kind == "tool_result"


def test_claude_writes_stdio_and_remote_mcp_config():
    adapter = ClaudeCodeAdapter()
    path = adapter._write_mcp_config(
        {
            "local": {"command": "npx", "args": ["server"], "env": {"TOKEN": "value"}},
            "remote": {
                "transport": "http",
                "url": "https://mcp.example.test",
                "headers": {"X-Team": "platform"},
                "bearer_token_env_var": "MCP_TOKEN",
            },
        }
    )
    assert path is not None
    try:
        config = json.loads(Path(path).read_text())
    finally:
        Path(path).unlink()
    assert config["mcpServers"]["local"]["command"] == "npx"
    remote = config["mcpServers"]["remote"]
    assert remote["type"] == "http"
    assert remote["headers"]["Authorization"] == "Bearer ${MCP_TOKEN}"


def test_claude_normalizes_explicitly_invoked_agent_tool_lists():
    adapter = ClaudeCodeAdapter()
    bindings = AdapterBindings(
        primary_directory=None,
        directories=[],
        mcp_servers={},
        tool_rules=[],
        agent_profiles={
            "reviewer": {
                "description": "Reviews changes",
                "prompt": "Review carefully.",
                "tools": "Bash, Read, Grep",
                "disallowedTools": "Write, Edit",
            }
        },
        skills={},
    )
    task = type(
        "TaskStub",
        (),
        {"model": None, "fallback_models": [], "thinking_level": None},
    )()
    project = type("ProjectStub", (), {"default_model": None})()

    flags = adapter._base_flags(task, project, bindings, {}, prompt="/reviewer check it")
    profiles = json.loads(flags[flags.index("--agents") + 1])

    assert profiles["reviewer"]["tools"] == ["Bash", "Read", "Grep"]
    assert profiles["reviewer"]["disallowedTools"] == ["Write", "Edit"]


def test_codex_renders_remote_mcp_flags_as_toml():
    bindings = AdapterBindings(
        primary_directory=None,
        directories=[],
        mcp_servers={
            "remote-api": {
                "transport": "http",
                "url": "https://mcp.example.test",
                "headers": {"X-Team": "platform"},
                "bearer_token_env_var": "MCP_TOKEN",
            }
        },
        tool_rules=[],
        agent_profiles={},
        skills={},
    )
    flags = CodexAdapter._capability_flags(type("TaskStub", (), {"thinking_level": None})(), bindings)
    rendered = " ".join(flags)
    assert 'mcp_servers.remote_api.url="https://mcp.example.test"' in rendered
    assert 'http_headers={ "X-Team" = "platform" }' in rendered
    assert 'bearer_token_env_var="MCP_TOKEN"' in rendered


def test_claude_applies_project_tool_permissions():
    bindings = AdapterBindings(
        primary_directory="/workspace/repo",
        directories=["/workspace/repo", "/workspace/shared"],
        mcp_servers={},
        tool_rules=[
            {"backend": "claude_code", "decision": "allow", "claude_pattern": "Bash(git *)", "codex_prefix": []},
            {"backend": "claude_code", "decision": "deny", "claude_pattern": "WebFetch", "codex_prefix": []},
        ],
        agent_profiles={},
        skills={},
    )
    task = type("TaskStub", (), {"model": None, "fallback_models": [], "thinking_level": None})()
    project = type("ProjectStub", (), {"default_model": None})()

    flags = ClaudeCodeAdapter()._base_flags(task, project, bindings, {})

    assert flags[flags.index("--permission-prompts") + 1] == "none"
    assert flags[flags.index("--allowedTools") + 1] == "Bash(git *)"
    assert flags[flags.index("--disallowedTools") + 1] == (
        "WebFetch,Bash(gh auth login *)"
    )
    assert flags.count("--add-dir") == 2


def test_codex_uses_primary_directory_and_additional_roots():
    bindings = AdapterBindings(
        primary_directory="/workspace/repo",
        directories=["/workspace/repo", "/workspace/shared"],
        mcp_servers={},
        tool_rules=[],
        agent_profiles={},
        skills={},
    )
    task = type("TaskStub", (), {"initial_prompt": "Fix it", "model": None, "thinking_level": None})()
    project = type("ProjectStub", (), {"default_model": None})()

    command = CodexAdapter().build_command(task, project, bindings, {})
    resumed = CodexAdapter().resume_command(task, project, bindings, {}, "session-id", "Continue")

    assert command.argv[command.argv.index("--cd") + 1] == "/workspace/repo"
    assert command.argv[command.argv.index("--add-dir") + 1] == "/workspace/shared"
    assert command.argv[command.argv.index("--sandbox") + 1] == "workspace-write"
    assert "--cd" not in resumed.argv
    assert "--add-dir" not in resumed.argv
    assert "--sandbox" not in resumed.argv
    assert command.argv[:4] == ["codex", "--no-daemon", "exec", "-"]
    assert command.stdin_payload is not None
    assert command.stdin_payload.endswith("Fix it")
    assert "no GitHub MCP connector" in command.stdin_payload
    assert resumed.argv[:7] == [
        "codex",
        "--no-daemon",
        "exec",
        "resume",
        "session-id",
        "-",
        "--json",
    ]
    assert resumed.stdin_payload is not None
    assert resumed.stdin_payload.endswith("Continue")


def test_fresh_session_commands_accept_runtime_handoff_prompt():
    bindings = AdapterBindings(
        primary_directory="/workspace/repo",
        directories=["/workspace/repo"],
        mcp_servers={},
        tool_rules=[],
        agent_profiles={},
        skills={},
    )
    task = type(
        "TaskStub",
        (),
        {
            "initial_prompt": "Original prompt",
            "model": None,
            "fallback_models": [],
            "thinking_level": None,
        },
    )()
    project = type("ProjectStub", (), {"default_model": None})()

    claude = ClaudeCodeAdapter().build_command(
        task, project, bindings, {}, "Runtime handoff"
    )
    codex = CodexAdapter().build_command(task, project, bindings, {}, "Runtime handoff")

    assert claude.argv[claude.argv.index("-p") + 1] == "Runtime handoff"
    assert claude.stdin_payload is None
    assert codex.stdin_payload is not None
    assert codex.stdin_payload.endswith("Runtime handoff")
    assert "Runtime handoff" not in codex.argv
    assert "Original prompt" not in codex.argv


def test_agent_and_skill_instructions_are_loaded_only_when_explicitly_invoked():
    bindings = AdapterBindings(
        primary_directory="/workspace/repo",
        directories=["/workspace/repo"],
        mcp_servers={},
        tool_rules=[],
        agent_profiles={
            "ui-agent": {
                "description": "UI agent",
                "prompt": "UI_AGENT_PRIVATE_INSTRUCTIONS",
            },
            "security-agent": {
                "description": "Security agent",
                "prompt": "SECURITY_AGENT_PRIVATE_INSTRUCTIONS",
            },
        },
        skills={
            "ui-review": "UI_SKILL_PRIVATE_INSTRUCTIONS",
            "security-review": "SECURITY_SKILL_PRIVATE_INSTRUCTIONS",
        },
    )
    task = type(
        "TaskStub",
        (),
        {
            "initial_prompt": "Fix the settings page",
            "backend": AgentBackend.codex,
            "model": None,
            "fallback_models": [],
            "thinking_level": None,
        },
    )()
    project = type(
        "ProjectStub",
        (),
        {"default_backend": AgentBackend.codex, "default_model": None},
    )()

    codex_plain = CodexAdapter().build_command(task, project, bindings, {})
    claude_plain = ClaudeCodeAdapter().build_command(task, project, bindings, {})
    codex_invoked = CodexAdapter().build_command(
        task,
        project,
        bindings,
        {},
        "/UI-REVIEW /ui-agent Fix the settings page",
    )
    claude_invoked = ClaudeCodeAdapter().build_command(
        task,
        project,
        bindings,
        {},
        "/ui-review /UI-AGENT Fix the settings page",
    )

    assert "UI_SKILL_PRIVATE_INSTRUCTIONS" not in (codex_plain.stdin_payload or "")
    assert "SECURITY_SKILL_PRIVATE_INSTRUCTIONS" not in (codex_plain.stdin_payload or "")
    assert "UI_SKILL_PRIVATE_INSTRUCTIONS" not in " ".join(claude_plain.argv)
    assert "SECURITY_SKILL_PRIVATE_INSTRUCTIONS" not in " ".join(claude_plain.argv)
    assert "UI_AGENT_PRIVATE_INSTRUCTIONS" not in (codex_plain.stdin_payload or "")
    assert "SECURITY_AGENT_PRIVATE_INSTRUCTIONS" not in (
        codex_plain.stdin_payload or ""
    )
    assert "UI_AGENT_PRIVATE_INSTRUCTIONS" not in " ".join(claude_plain.argv)
    assert "SECURITY_AGENT_PRIVATE_INSTRUCTIONS" not in " ".join(claude_plain.argv)

    assert "UI_SKILL_PRIVATE_INSTRUCTIONS" in (codex_invoked.stdin_payload or "")
    assert "SECURITY_SKILL_PRIVATE_INSTRUCTIONS" not in (
        codex_invoked.stdin_payload or ""
    )
    assert "UI_AGENT_PRIVATE_INSTRUCTIONS" in (codex_invoked.stdin_payload or "")
    assert "SECURITY_AGENT_PRIVATE_INSTRUCTIONS" not in (
        codex_invoked.stdin_payload or ""
    )
    claude_system = claude_invoked.argv[
        claude_invoked.argv.index("--append-system-prompt") + 1
    ]
    assert "UI_SKILL_PRIVATE_INSTRUCTIONS" in claude_system
    assert "SECURITY_SKILL_PRIVATE_INSTRUCTIONS" not in claude_system
    claude_agents = json.loads(
        claude_invoked.argv[claude_invoked.argv.index("--agents") + 1]
    )
    assert set(claude_agents) == {"ui-agent"}
    assert claude_agents["ui-agent"]["prompt"] == "UI_AGENT_PRIVATE_INSTRUCTIONS"


def test_project_default_model_does_not_cross_runtime_boundary():
    bindings = AdapterBindings(
        primary_directory="/workspace/repo",
        directories=["/workspace/repo"],
        mcp_servers={},
        tool_rules=[],
        agent_profiles={},
        skills={},
    )
    task = type(
        "TaskStub",
        (),
        {
            "initial_prompt": "Continue",
            "backend": AgentBackend.codex,
            "model": None,
            "thinking_level": None,
        },
    )()
    project = type(
        "ProjectStub",
        (),
        {
            "default_backend": AgentBackend.claude_code,
            "default_model": "claude-sonnet",
        },
    )()

    command = CodexAdapter().build_command(task, project, bindings, {})

    assert "--model" not in command.argv
    assert "claude-sonnet" not in command.argv


def test_codex_home_overlay_layers_project_rules(monkeypatch, tmp_path):
    source_home = tmp_path / "codex"
    source_home.mkdir()
    (source_home / "auth.json").write_text("{}")
    source_rules = source_home / "rules"
    source_rules.mkdir()
    (source_rules / "default.rules").write_text(
        'prefix_rule(pattern=["git", "status"], decision="allow")\n'
    )
    monkeypatch.setenv("CODEX_HOME", str(source_home))

    overlay = create_codex_home_overlay(
        [{"backend": "codex", "decision": "allow", "codex_prefix": ["git", "push"]}],
        tmp_path / "muster-data" / "backend-sessions" / "task-123" / "codex",
    )

    assert overlay is not None
    assert (overlay / "auth.json").is_symlink()
    assert 'pattern=["git", "push"]' in (overlay / "rules" / "muster.rules").read_text()
    assert 'pattern=["gh", "auth", "login"]' in (
        overlay / "rules" / "muster.rules"
    ).read_text()
    assert (overlay / "rules" / "user-default.rules").is_symlink()
    shutil.rmtree(overlay)


def test_codex_home_overlay_reuses_persistent_task_directory(monkeypatch, tmp_path):
    source_home = tmp_path / "codex"
    source_home.mkdir()
    sessions = source_home / "sessions"
    sessions.mkdir()
    (sessions / "global-thread.jsonl").write_text("global\n")
    monkeypatch.setenv("CODEX_HOME", str(source_home))
    task_home = tmp_path / "muster-data" / "backend-sessions" / "task-123" / "codex"

    first = create_codex_home_overlay([], task_home)
    assert not (first / "sessions").exists()
    (first / "sessions").mkdir()
    rollout = first / "sessions" / "rollout-thread-123.jsonl"
    rollout.write_text("{}\n")
    second = create_codex_home_overlay([], task_home)

    assert first == second == task_home
    assert not (second / "sessions").is_symlink()
    assert rollout.read_text() == "{}\n"
    assert not (second / "sessions" / "global-thread.jsonl").exists()
    assert not (sessions / "rollout-thread-123.jsonl").exists()


def test_codex_home_overlay_removes_legacy_global_runtime_symlinks(monkeypatch, tmp_path):
    source_home = tmp_path / "codex"
    source_home.mkdir()
    sessions = source_home / "sessions"
    sessions.mkdir()
    state = source_home / "state_5.sqlite"
    state.write_bytes(b"global state")
    monkeypatch.setenv("CODEX_HOME", str(source_home))
    task_home = tmp_path / "task-home"
    task_home.mkdir()
    (task_home / "sessions").symlink_to(sessions, target_is_directory=True)
    (task_home / "state_5.sqlite").symlink_to(state)

    create_codex_home_overlay([], task_home)

    assert not (task_home / "sessions").is_symlink()
    assert not (task_home / "sessions").exists()
    assert not (task_home / "state_5.sqlite").is_symlink()
    assert not (task_home / "state_5.sqlite").exists()
    assert sessions.is_dir()
    assert state.read_bytes() == b"global state"


def test_codex_home_overlay_preserves_legacy_links_for_known_resume_session(
    monkeypatch, tmp_path
):
    source_home = tmp_path / "codex"
    source_home.mkdir()
    sessions = source_home / "sessions"
    sessions.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(source_home))
    task_home = tmp_path / "task-home"
    task_home.mkdir()
    legacy_sessions = task_home / "sessions"
    legacy_sessions.symlink_to(sessions, target_is_directory=True)

    create_codex_home_overlay(
        [],
        task_home,
        preserve_legacy_session=True,
    )

    assert legacy_sessions.is_symlink()
    assert legacy_sessions.resolve() == sessions.resolve()


def test_github_mcp_guidance_prevents_interactive_cli_login():
    bindings = AdapterBindings(
        primary_directory="/workspace/repo",
        directories=["/workspace/repo"],
        mcp_servers={"github": {"url": "https://mcp.example.test"}},
        tool_rules=[],
        agent_profiles={},
        skills={},
    )
    task = type(
        "TaskStub",
        (),
        {
            "initial_prompt": "Update the PR",
            "model": None,
            "fallback_models": [],
            "thinking_level": None,
        },
    )()
    project = type("ProjectStub", (), {"default_model": None})()

    codex = CodexAdapter().build_command(task, project, bindings, {})
    claude = ClaudeCodeAdapter().build_command(task, project, bindings, {})
    claude_system = claude.argv[claude.argv.index("--append-system-prompt") + 1]

    assert "Use its tools to create or update pull requests" in (codex.stdin_payload or "")
    assert "Never run `gh auth login`" in (codex.stdin_payload or "")
    assert "Use its tools to create or update pull requests" in claude_system


def test_codex_repairs_stale_rollout_path_from_real_sessions(monkeypatch, tmp_path):
    codex_home = tmp_path / "codex"
    rollout = codex_home / "sessions" / "2026" / "09" / "25" / (
        "rollout-2026-09-25T12-35-17-thread-123.jsonl"
    )
    rollout.parent.mkdir(parents=True)
    rollout.write_text("{}\n")
    state_db = codex_home / "state_5.sqlite"
    with sqlite3.connect(state_db) as connection:
        connection.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT)")
        connection.execute(
            "INSERT INTO threads (id, rollout_path) VALUES (?, ?)",
            ("thread-123", str(tmp_path / "deleted-temp" / rollout.name)),
        )
        connection.commit()
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    assert repair_codex_rollout_path("thread-123") is True
    with sqlite3.connect(state_db) as connection:
        repaired = connection.execute(
            "SELECT rollout_path FROM threads WHERE id = 'thread-123'"
        ).fetchone()
    assert repaired == (str(rollout.resolve()),)


def test_codex_replaces_live_legacy_temp_symlink(monkeypatch, tmp_path):
    codex_home = tmp_path / "codex"
    rollout = codex_home / "sessions" / "2026" / "09" / "25" / (
        "rollout-2026-09-25T12-35-17-thread-456.jsonl"
    )
    rollout.parent.mkdir(parents=True)
    rollout.write_text("{}\n")
    legacy_sessions = tmp_path / "muster-codex-home-old" / "sessions"
    legacy_sessions.parent.mkdir()
    legacy_sessions.symlink_to(codex_home / "sessions", target_is_directory=True)
    legacy_rollout = legacy_sessions / rollout.relative_to(codex_home / "sessions")
    state_db = codex_home / "state_5.sqlite"
    with sqlite3.connect(state_db) as connection:
        connection.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT)")
        connection.execute(
            "INSERT INTO threads (id, rollout_path) VALUES (?, ?)",
            ("thread-456", str(legacy_rollout)),
        )
        connection.commit()
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    assert legacy_rollout.is_file()
    assert repair_codex_rollout_path("thread-456") is True
    with sqlite3.connect(state_db) as connection:
        repaired = connection.execute(
            "SELECT rollout_path FROM threads WHERE id = 'thread-456'"
        ).fetchone()
    assert repaired == (str(rollout.resolve()),)
