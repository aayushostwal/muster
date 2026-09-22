"""Codex CLI adapter (see docs/SPEC.md "Agent backends" -> codex.py)."""
from __future__ import annotations

import json

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


class CodexAdapter:
    """Wraps the `codex exec ... --json` non-interactive mode."""

    backend = AgentBackend.codex

    def build_command(
        self,
        task: Task,
        project: Project,
        bindings: AdapterBindings,
        secrets: dict[str, str],
    ) -> list[str]:
        cmd = [settings.codex_bin, "exec", task.initial_prompt, "--json"]
        model = task.model or project.default_model
        if model:
            cmd += ["--model", model]
        for directory in bindings.directories:
            # Codex CLI grants filesystem access via a repeated --cd/--sandbox
            # writable-dir style flag; mirrored here as --add-dir for parity
            # with the claude adapter until the real Codex flag is confirmed
            # (see SPEC.md note on `musterctl doctor` surfacing CLI mismatches).
            cmd += ["--add-dir", directory]
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
        cmd = [settings.codex_bin, "exec", "resume", session_id, prompt, "--json"]
        model = task.model or project.default_model
        if model:
            cmd += ["--model", model]
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

        event_type = event.get("type") or event.get("msg", {}).get("type")
        session_id = event.get("session_id") or event.get("id")

        if event_type in ("agent_message", "assistant", "item.completed"):
            text = self._extract_text(event)
            if text:
                return AgentText(text=text)
            return None

        if event_type in ("task_complete", "result"):
            return Done(raw=event)

        if event_type in ("approval_request", "exec_approval_request", "patch_approval_request"):
            text = event.get("message") or event.get("reason") or json.dumps(event)
            return BlockingQuestion(text=text)

        if event_type == "session_configured" and session_id:
            return SessionId(session_id=str(session_id))

        if event_type == "error":
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
        return ""
