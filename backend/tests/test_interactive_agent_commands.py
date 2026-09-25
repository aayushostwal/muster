from __future__ import annotations

from types import SimpleNamespace

from app.db.models import AgentBackend
from app.services.agent_backends.base import AdapterBindings
from app.services.agent_backends.claude_code import ClaudeCodeAdapter
from app.services.agent_backends.codex import CodexAdapter


def _bindings(tmp_path) -> AdapterBindings:
    return AdapterBindings(
        primary_directory=str(tmp_path),
        directories=[str(tmp_path)],
        mcp_servers={},
        tool_rules=[],
        agent_profiles={},
        skills={},
    )


def _task(backend: AgentBackend):
    return SimpleNamespace(
        backend=backend,
        initial_prompt="fix the bug",
        model="test-model",
        fallback_models=[],
        thinking_level="high",
    )


def _project(backend: AgentBackend):
    return SimpleNamespace(default_backend=backend, default_model=None)


def test_codex_interactive_command_uses_tui_not_exec(tmp_path):
    command = CodexAdapter().build_interactive_command(
        _task(AgentBackend.codex),
        _project(AgentBackend.codex),
        _bindings(tmp_path),
        {},
    )

    assert command.argv[0] == "codex"
    assert "exec" not in command.argv
    assert command.argv[-1].endswith("fix the bug")
    assert command.stdin_payload is None
    assert "--ask-for-approval" in command.argv


def test_claude_interactive_command_omits_print_only_flags(tmp_path):
    command = ClaudeCodeAdapter().build_interactive_command(
        _task(AgentBackend.claude_code),
        _project(AgentBackend.claude_code),
        _bindings(tmp_path),
        {},
    )

    assert command.argv[0] == "claude"
    assert "-p" not in command.argv
    assert "--output-format" not in command.argv
    assert "--permission-prompts" not in command.argv
    assert command.argv[-1] == "fix the bug"
