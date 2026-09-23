"""Contract tests for the structured CLI event streams shown in the activity UI."""
from __future__ import annotations

import json
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


def test_claude_normalizes_imported_agent_tool_lists():
    adapter = ClaudeCodeAdapter()
    bindings = AdapterBindings(
        directories=[],
        mcp_servers={},
        tool_names=[],
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

    flags = adapter._base_flags(task, project, bindings, {})
    profiles = json.loads(flags[flags.index("--agents") + 1])

    assert profiles["reviewer"]["tools"] == ["Bash", "Read", "Grep"]
    assert profiles["reviewer"]["disallowedTools"] == ["Write", "Edit"]


def test_codex_renders_remote_mcp_flags_as_toml():
    bindings = AdapterBindings(
        directories=[],
        mcp_servers={
            "remote-api": {
                "transport": "http",
                "url": "https://mcp.example.test",
                "headers": {"X-Team": "platform"},
                "bearer_token_env_var": "MCP_TOKEN",
            }
        },
        tool_names=[],
        agent_profiles={},
        skills={},
    )
    flags = CodexAdapter._capability_flags(type("TaskStub", (), {"thinking_level": None})(), bindings)
    rendered = " ".join(flags)
    assert 'mcp_servers.remote_api.url="https://mcp.example.test"' in rendered
    assert 'http_headers={ "X-Team" = "platform" }' in rendered
    assert 'bearer_token_env_var="MCP_TOKEN"' in rendered
