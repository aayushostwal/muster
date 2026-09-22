"""Claude Code CLI adapter (see docs/SPEC.md "Agent backends" -> claude_code.py)."""
from __future__ import annotations

import json
import tempfile

from app.config import settings
from app.db.models import AgentBackend, Project, Task
from app.services.agent_backends.base import (
    AdapterBindings,
    AgentText,
    BlockingQuestion,
    Done,
    ErrorEvent,
    ParsedEvent,
    SessionId,
)


class ClaudeCodeAdapter:
    """Wraps the `claude` CLI's headless (`-p`) stream-json mode."""

    backend = AgentBackend.claude_code

    def _write_mcp_config(self, mcp_servers: dict[str, dict]) -> str | None:
        """Write the Project's MCP bindings to a temp JSON file for --mcp-config.

        Returns the file path, or None if there are no MCP servers bound.
        """
        if not mcp_servers:
            return None
        config = {
            "mcpServers": {
                name: {
                    "command": cfg.get("command"),
                    "args": cfg.get("args", []),
                    "env": cfg.get("env", {}),
                }
                for name, cfg in mcp_servers.items()
            }
        }
        fd = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", prefix="muster-mcp-", delete=False
        )
        try:
            json.dump(config, fd)
        finally:
            fd.close()
        return fd.name

    def _base_flags(
        self,
        task: Task,
        project: Project,
        bindings: AdapterBindings,
        secrets: dict[str, str],
    ) -> list[str]:
        flags: list[str] = [
            "--output-format",
            "stream-json",
            # The CLI requires --verbose whenever --print is combined with
            # --output-format stream-json (confirmed against the real `claude`
            # binary: "Error: When using --print, --output-format=stream-json
            # requires --verbose").
            "--verbose",
            "--permission-mode",
            "acceptEdits",
        ]
        for directory in bindings.directories:
            flags += ["--add-dir", directory]

        mcp_config_path = self._write_mcp_config(bindings.mcp_servers)
        if mcp_config_path:
            flags += ["--mcp-config", mcp_config_path]

        model = task.model or project.default_model
        if model:
            flags += ["--model", model]

        return flags

    def build_command(
        self,
        task: Task,
        project: Project,
        bindings: AdapterBindings,
        secrets: dict[str, str],
    ) -> list[str]:
        cmd = [settings.claude_code_bin, "-p", task.initial_prompt]
        cmd += self._base_flags(task, project, bindings, secrets)
        return cmd

    def resume_command(
        self,
        task: Task,
        project: Project,
        bindings: AdapterBindings,
        secrets: dict[str, str],
        session_id: str,
        prompt: str,
    ) -> list[str]:
        cmd = [settings.claude_code_bin, "--resume", session_id, "-p", prompt]
        cmd += self._base_flags(task, project, bindings, secrets)
        return cmd

    def parse_line(self, raw: str) -> ParsedEvent | None:
        raw = raw.strip()
        if not raw:
            return None
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return None

        if not isinstance(event, dict):
            return None

        session_id = event.get("session_id")
        event_type = event.get("type")

        if event_type == "assistant":
            text = self._extract_assistant_text(event)
            if text:
                return AgentText(text=text)
            return None

        if event_type == "result":
            if event.get("subtype") == "success":
                return Done(raw=event)
            return ErrorEvent(message=event.get("error") or json.dumps(event))

        if event_type in ("permission_denial", "permission_request"):
            text = event.get("message") or event.get("reason") or json.dumps(event)
            return BlockingQuestion(text=text)

        # A tool_use block requiring approval, surfaced inline in an assistant
        # message without full `--permission-mode acceptEdits` coverage.
        if event_type == "tool_use" and event.get("requires_approval"):
            return BlockingQuestion(text=event.get("message") or json.dumps(event))

        if session_id:
            return SessionId(session_id=session_id)

        if event_type == "error":
            return ErrorEvent(message=event.get("message") or json.dumps(event))

        return None

    @staticmethod
    def _extract_assistant_text(event: dict) -> str:
        message = event.get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            return "".join(parts)
        return ""
