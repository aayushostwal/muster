"""Claude Code CLI adapter (see docs/SPEC.md "Agent backends" -> claude_code.py)."""
from __future__ import annotations

import json
import tempfile

from app.config import settings
from app.db.models import AgentBackend, Project, Task
from app.services.agent_backends.base import (
    AdapterBindings,
    ActivityEvent,
    AgentText,
    BackendCommand,
    Done,
    ErrorEvent,
    ParsedEvent,
    PermissionRequest,
    SessionId,
    UsageEvent,
)


class ClaudeCodeAdapter:
    """Wraps the `claude` CLI's headless (`-p`) stream-json mode."""

    backend = AgentBackend.claude_code

    @staticmethod
    def _normalize_agent_profiles(agent_profiles: dict[str, dict]) -> dict[str, dict]:
        """Convert imported frontmatter values to Claude's --agents JSON schema."""
        normalized: dict[str, dict] = {}
        for name, profile in agent_profiles.items():
            definition = dict(profile)
            for field in ("tools", "disallowedTools"):
                value = definition.get(field)
                if isinstance(value, str):
                    definition[field] = [item.strip() for item in value.split(",") if item.strip()]
                elif isinstance(value, list):
                    definition[field] = [str(item).strip() for item in value if str(item).strip()]
                elif value is not None:
                    definition.pop(field)
            normalized[name] = definition
        return normalized

    def _write_mcp_config(self, mcp_servers: dict[str, dict]) -> str | None:
        """Write the Project's MCP bindings to a temp JSON file for --mcp-config.

        Returns the file path, or None if there are no MCP servers bound.
        """
        if not mcp_servers:
            return None
        servers: dict[str, dict] = {}
        for name, cfg in mcp_servers.items():
            transport = cfg.get("transport", "stdio")
            if transport == "stdio":
                servers[name] = {
                    "command": cfg.get("command"),
                    "args": cfg.get("args", []),
                    "env": cfg.get("env", {}),
                }
                continue

            headers = dict(cfg.get("headers") or {})
            bearer_env = cfg.get("bearer_token_env_var")
            if bearer_env and "Authorization" not in headers:
                headers["Authorization"] = f"Bearer ${{{bearer_env}}}"
            servers[name] = {
                "type": "sse" if transport == "sse" else "http",
                "url": cfg.get("url"),
                "headers": headers,
            }
        config = {"mcpServers": servers}
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
            "--permission-prompts",
            "none",
            "--include-hook-events",
            "--forward-subagent-text",
        ]
        for directory in bindings.directories:
            flags += ["--add-dir", directory]

        allowed_tools = [
            rule["claude_pattern"]
            for rule in bindings.tool_rules
            if rule.get("decision") == "allow"
            and rule.get("backend") in {"all", "claude_code"}
            and rule.get("claude_pattern")
        ]
        denied_tools = [
            rule["claude_pattern"]
            for rule in bindings.tool_rules
            if rule.get("decision") == "deny"
            and rule.get("backend") in {"all", "claude_code"}
            and rule.get("claude_pattern")
        ]
        if allowed_tools:
            flags += ["--allowedTools", ",".join(allowed_tools)]
        if denied_tools:
            flags += ["--disallowedTools", ",".join(denied_tools)]

        mcp_config_path = self._write_mcp_config(bindings.mcp_servers)
        if mcp_config_path:
            flags += ["--mcp-config", mcp_config_path]

        model = task.model or (
            project.default_model
            if getattr(task, "backend", None) == getattr(project, "default_backend", None)
            else None
        )
        if model:
            flags += ["--model", model]

        if task.fallback_models:
            flags += ["--fallback-model", ",".join(task.fallback_models)]
        if task.thinking_level:
            flags += ["--effort", task.thinking_level]
        if bindings.agent_profiles:
            flags += [
                "--agents",
                json.dumps(self._normalize_agent_profiles(bindings.agent_profiles)),
            ]
        system_sections = []
        if bindings.selected_agent_prompt:
            system_sections.append(bindings.selected_agent_prompt)
        if bindings.skills:
            rendered = "\n\n".join(
                f"Skill: {name}\n{instructions}" for name, instructions in bindings.skills.items()
            )
            system_sections.append(f"Available Muster skills:\n\n{rendered}")
        if system_sections:
            flags += ["--append-system-prompt", "\n\n".join(system_sections)]

        return flags

    def build_command(
        self,
        task: Task,
        project: Project,
        bindings: AdapterBindings,
        secrets: dict[str, str],
        prompt: str | None = None,
    ) -> BackendCommand:
        cmd = [settings.claude_code_bin, "-p", prompt or task.initial_prompt]
        cmd += self._base_flags(task, project, bindings, secrets)
        return BackendCommand(argv=cmd)

    def resume_command(
        self,
        task: Task,
        project: Project,
        bindings: AdapterBindings,
        secrets: dict[str, str],
        session_id: str,
        prompt: str,
    ) -> BackendCommand:
        cmd = [settings.claude_code_bin, "--resume", session_id, "-p", prompt]
        cmd += self._base_flags(task, project, bindings, secrets)
        return BackendCommand(argv=cmd)

    def parse_line(self, raw: str) -> ParsedEvent | list[ParsedEvent] | None:
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
            parsed: list[ParsedEvent] = []
            if session_id:
                parsed.append(SessionId(session_id=str(session_id)))
            text = self._extract_assistant_text(event)
            if text:
                parsed.append(AgentText(text=text))
            message = event.get("message") or {}
            for block in message.get("content", []) if isinstance(message, dict) else []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    name = str(block.get("name") or "Tool call")
                    kind = "agent_call" if name.lower() in {"task", "agent", "subagent"} else "tool_call"
                    parsed.append(ActivityEvent(kind=kind, title=name, content=json.dumps(block.get("input", {}), indent=2), metadata={"tool_use_id": block.get("id")}))
                elif block.get("type") in {"thinking", "reasoning"}:
                    parsed.append(ActivityEvent(kind="reasoning", title="Reasoning", content=block.get("thinking") or block.get("text")))
            return parsed or None

        if event_type == "user":
            parsed_user: list[ParsedEvent] = []
            if session_id:
                parsed_user.append(SessionId(session_id=str(session_id)))
            message = event.get("message") or {}
            for block in message.get("content", []) if isinstance(message, dict) else []:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                content = block.get("content")
                rendered = content if isinstance(content, str) else json.dumps(content, indent=2)
                parsed_user.append(
                    ActivityEvent(
                        kind="tool_result",
                        title="Tool result",
                        content=rendered,
                        metadata={"tool_use_id": block.get("tool_use_id"), "is_error": block.get("is_error", False)},
                    )
                )
            return parsed_user or None

        if event_type == "result":
            usage = event.get("usage") or {}
            parsed_result: list[ParsedEvent] = []
            if session_id:
                parsed_result.append(SessionId(session_id=str(session_id)))
            if usage:
                parsed_result.append(UsageEvent(input_tokens=int(usage.get("input_tokens", 0) or 0), output_tokens=int(usage.get("output_tokens", 0) or 0), cached_tokens=int(usage.get("cache_read_input_tokens", 0) or 0) + int(usage.get("cache_creation_input_tokens", 0) or 0)))
            if event.get("subtype") == "success":
                parsed_result.append(Done(raw=event))
            else:
                parsed_result.append(ErrorEvent(message=event.get("error") or json.dumps(event)))
            return parsed_result

        if event_type in ("permission_denial", "permission_request"):
            text = event.get("message") or event.get("reason") or json.dumps(event)
            return PermissionRequest(
                tool_name=str(event.get("tool_name") or event.get("tool") or "Tool"),
                tool_input=event.get("input") if isinstance(event.get("input"), dict) else {},
                reason=text,
            )

        # A tool_use block requiring approval, surfaced inline in an assistant
        # message without full `--permission-mode acceptEdits` coverage.
        if event_type == "tool_use" and event.get("requires_approval"):
            return PermissionRequest(
                tool_name=str(event.get("name") or "Tool"),
                tool_input=event.get("input") if isinstance(event.get("input"), dict) else {},
                reason=event.get("message") or json.dumps(event),
            )

        if session_id:
            return SessionId(session_id=session_id)

        if event_type == "error":
            return ErrorEvent(message=event.get("message") or json.dumps(event))

        if event_type in {"hook_started", "hook_response", "progress"}:
            return ActivityEvent(kind="log", title=event_type.replace("_", " ").title(), content=json.dumps(event, indent=2))

        if event_type == "tool_result":
            return ActivityEvent(kind="tool_result", title="Tool result", content=json.dumps(event, indent=2))

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
