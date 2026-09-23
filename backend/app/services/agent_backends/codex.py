"""Codex CLI adapter (see docs/SPEC.md "Agent backends" -> codex.py)."""
from __future__ import annotations

import json

from app.config import settings
from app.db.models import AgentBackend, Project, Task
from app.services.agent_backends.base import (
    AdapterBindings,
    ActivityEvent,
    AgentText,
    BlockingQuestion,
    Done,
    ErrorEvent,
    ParsedEvent,
    SessionId,
    UsageEvent,
)


class CodexAdapter:
    """Wraps the `codex exec ... --json` non-interactive mode."""

    backend = AgentBackend.codex

    @staticmethod
    def _toml_inline_table(values: dict[str, str]) -> str:
        return "{ " + ", ".join(
            f"{json.dumps(key)} = {json.dumps(value)}" for key, value in values.items()
        ) + " }"

    @staticmethod
    def _prompt(task: Task, bindings: AdapterBindings, prompt: str) -> str:
        sections = []
        if bindings.selected_agent_prompt:
            sections.append(f"Agent profile:\n{bindings.selected_agent_prompt}")
        if bindings.skills:
            skills = "\n\n".join(f"Skill: {name}\n{body}" for name, body in bindings.skills.items())
            sections.append(f"Available Muster skills:\n{skills}")
        if bindings.agent_profiles:
            agents = "\n\n".join(
                f"Agent: {name}\nRole: {profile.get('description', name)}\nInstructions: {profile.get('prompt', '')}"
                for name, profile in bindings.agent_profiles.items()
            )
            sections.append(
                "Available Muster sub-agent profiles. When delegating, use the matching role and "
                f"include its instructions in the delegated task:\n{agents}"
            )
        sections.append(prompt)
        return "\n\n---\n\n".join(sections)

    @staticmethod
    def _capability_flags(task: Task, bindings: AdapterBindings) -> list[str]:
        flags: list[str] = []
        if task.thinking_level:
            flags += ["-c", f'model_reasoning_effort="{task.thinking_level}"']
        for name, config in bindings.mcp_servers.items():
            safe_name = name.replace("-", "_").replace(" ", "_")
            if config.get("url"):
                flags += ["-c", f'mcp_servers.{safe_name}.url={json.dumps(config["url"])}']
            if config.get("command"):
                flags += ["-c", f'mcp_servers.{safe_name}.command={json.dumps(config["command"])}']
            if config.get("args"):
                flags += ["-c", f'mcp_servers.{safe_name}.args={json.dumps(config["args"])}']
            if config.get("env"):
                flags += [
                    "-c",
                    f'mcp_servers.{safe_name}.env={CodexAdapter._toml_inline_table(config["env"])}',
                ]
            if config.get("headers"):
                flags += [
                    "-c",
                    f'mcp_servers.{safe_name}.http_headers={CodexAdapter._toml_inline_table(config["headers"])}',
                ]
            if config.get("bearer_token_env_var"):
                flags += [
                    "-c",
                    f'mcp_servers.{safe_name}.bearer_token_env_var={json.dumps(config["bearer_token_env_var"])}',
                ]
        return flags

    def build_command(
        self,
        task: Task,
        project: Project,
        bindings: AdapterBindings,
        secrets: dict[str, str],
    ) -> list[str]:
        cmd = [settings.codex_bin, "exec", self._prompt(task, bindings, task.initial_prompt), "--json"]
        model = task.model or project.default_model
        if model:
            cmd += ["--model", model]
        for directory in bindings.directories:
            # Codex CLI grants filesystem access via a repeated --cd/--sandbox
            # writable-dir style flag; mirrored here as --add-dir for parity
            # with the claude adapter until the real Codex flag is confirmed
            # (see SPEC.md note on `musterctl doctor` surfacing CLI mismatches).
            cmd += ["--add-dir", directory]
        cmd += self._capability_flags(task, bindings)
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
        cmd = [settings.codex_bin, "exec", "resume", session_id, self._prompt(task, bindings, prompt), "--json"]
        model = task.model or project.default_model
        if model:
            cmd += ["--model", model]
        cmd += self._capability_flags(task, bindings)
        return cmd

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

        event_type = event.get("type") or event.get("msg", {}).get("type")
        session_id = event.get("thread_id") or event.get("session_id")

        item = event.get("item") if isinstance(event.get("item"), dict) else {}
        item_type = item.get("type")

        if event_type in ("agent_message", "assistant") or item_type == "agent_message":
            text = self._extract_text(event)
            if text:
                return AgentText(text=text)
            return None

        if event_type in ("item.started", "item.completed") and item_type:
            kind_map = {
                "command_execution": "tool_call" if event_type == "item.started" else "tool_result",
                "file_change": "diff",
                "mcp_tool_call": "tool_call" if event_type == "item.started" else "tool_result",
                "collab_agent_tool_call": "agent_call",
                "reasoning": "reasoning",
            }
            if item_type in kind_map:
                content = item.get("diff") or item.get("output") or item.get("command") or item.get("text")
                return ActivityEvent(kind=kind_map[item_type], title=str(item.get("name") or item_type.replace("_", " ").title()), content=content if isinstance(content, str) else json.dumps(content, indent=2) if content is not None else None, metadata={"status": item.get("status"), "item_id": item.get("id")})

        if event_type in ("turn.completed", "task_complete", "result"):
            usage = event.get("usage") or event.get("token_usage") or {}
            parsed: list[ParsedEvent] = []
            if usage:
                parsed.append(UsageEvent(input_tokens=int(usage.get("input_tokens", 0) or 0), output_tokens=int(usage.get("output_tokens", 0) or 0), cached_tokens=int(usage.get("cached_input_tokens", 0) or 0)))
            parsed.append(Done(raw=event))
            return parsed

        if event_type in ("approval_request", "exec_approval_request", "patch_approval_request"):
            text = event.get("message") or event.get("reason") or json.dumps(event)
            return BlockingQuestion(text=text)

        if event_type in ("thread.started", "session_configured") and session_id:
            return SessionId(session_id=str(session_id))

        if event_type in ("error", "turn.failed"):
            return ErrorEvent(message=event.get("message") or json.dumps(event))

        return None

    @staticmethod
    def _extract_text(event: dict) -> str:
        if isinstance(event.get("text"), str):
            return event["text"]
        msg = event.get("msg")
        if isinstance(msg, dict) and isinstance(msg.get("message"), str):
            return msg["message"]
        message = event.get("message")
        if isinstance(message, str):
            return message
        item = event.get("item")
        if isinstance(item, dict):
            if isinstance(item.get("text"), str):
                return item["text"]
            if isinstance(item.get("message"), str):
                return item["message"]
        return ""
