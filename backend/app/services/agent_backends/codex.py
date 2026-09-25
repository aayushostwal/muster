"""Codex CLI adapter (see docs/SPEC.md "Agent backends" -> codex.py)."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

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
    pull_request_guidance,
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
        sections.append(pull_request_guidance(bindings))
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
        prompt: str | None = None,
    ) -> BackendCommand:
        rendered_prompt = self._prompt(task, bindings, prompt or task.initial_prompt)
        cmd = [settings.codex_bin, "exec", "-", "--json"]
        model = task.model or (
            project.default_model
            if getattr(task, "backend", None) == getattr(project, "default_backend", None)
            else None
        )
        if model:
            cmd += ["--model", model]
        cmd += ["--sandbox", "workspace-write", "-c", 'approval_policy="on-request"']
        if bindings.primary_directory:
            cmd += ["--cd", bindings.primary_directory]
        for directory in bindings.directories:
            if directory != bindings.primary_directory:
                cmd += ["--add-dir", directory]
        cmd += self._capability_flags(task, bindings)
        return BackendCommand(argv=cmd, stdin_payload=rendered_prompt)

    def resume_command(
        self,
        task: Task,
        project: Project,
        bindings: AdapterBindings,
        secrets: dict[str, str],
        session_id: str,
        prompt: str,
    ) -> BackendCommand:
        rendered_prompt = self._prompt(task, bindings, prompt)
        cmd = [settings.codex_bin, "exec", "resume", session_id, "-", "--json"]
        model = task.model or (
            project.default_model
            if getattr(task, "backend", None) == getattr(project, "default_backend", None)
            else None
        )
        if model:
            cmd += ["--model", model]
        # `exec resume` restores the original sandbox and writable roots and
        # does not accept `--cd`, `--add-dir`, or `--sandbox` again.
        cmd += ["-c", 'approval_policy="on-request"']
        cmd += self._capability_flags(task, bindings)
        return BackendCommand(argv=cmd, stdin_payload=rendered_prompt)

    def build_interactive_command(
        self,
        task: Task,
        project: Project,
        bindings: AdapterBindings,
        secrets: dict[str, str],
        prompt: str | None = None,
    ) -> BackendCommand:
        rendered_prompt = self._prompt(task, bindings, prompt or task.initial_prompt)
        cmd = [settings.codex_bin]
        model = task.model or (
            project.default_model
            if getattr(task, "backend", None) == getattr(project, "default_backend", None)
            else None
        )
        if model:
            cmd += ["--model", model]
        cmd += ["--sandbox", "workspace-write", "--ask-for-approval", "on-request"]
        if bindings.primary_directory:
            cmd += ["--cd", bindings.primary_directory]
        for directory in bindings.directories:
            if directory != bindings.primary_directory:
                cmd += ["--add-dir", directory]
        cmd += self._capability_flags(task, bindings)
        cmd.append(rendered_prompt)
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
                status = item.get("status")
                return ActivityEvent(
                    kind=kind_map[item_type],
                    title=str(item.get("name") or item_type.replace("_", " ").title()),
                    content=(
                        content
                        if isinstance(content, str)
                        else json.dumps(content, indent=2)
                        if content is not None
                        else None
                    ),
                    metadata={
                        "status": status,
                        "item_id": item.get("id"),
                        "is_error": status in {"failed", "denied"}
                        or bool(item.get("exit_code")),
                    },
                )

        if event_type in ("turn.completed", "task_complete", "result"):
            usage = event.get("usage") or event.get("token_usage") or {}
            parsed: list[ParsedEvent] = []
            if usage:
                parsed.append(UsageEvent(input_tokens=int(usage.get("input_tokens", 0) or 0), output_tokens=int(usage.get("output_tokens", 0) or 0), cached_tokens=int(usage.get("cached_input_tokens", 0) or 0)))
            parsed.append(Done(raw=event))
            return parsed

        if event_type in ("approval_request", "exec_approval_request", "patch_approval_request"):
            request = event.get("request") if isinstance(event.get("request"), dict) else event
            command = request.get("command") or request.get("cmd") or request.get("changes")
            return PermissionRequest(
                tool_name="Shell" if command else "File change",
                tool_input={"command": command} if command is not None else request,
                reason=event.get("message") or event.get("reason"),
            )

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


def create_codex_home_overlay(tool_rules: list[dict], overlay: Path) -> Path:
    """Layer project rules into a persistent, task-scoped Codex home."""
    codex_rules = [
        rule
        for rule in tool_rules
        if rule.get("backend") in {"all", "codex"} and rule.get("codex_prefix")
    ]
    source_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    overlay.mkdir(parents=True, exist_ok=True)
    overlay.chmod(0o700)
    for source in source_home.iterdir() if source_home.exists() else ():
        if source.name == "rules":
            continue
        destination = overlay / source.name
        if not destination.exists() and not destination.is_symlink():
            destination.symlink_to(source, target_is_directory=source.is_dir())

    rules_dir = overlay / "rules"
    rules_dir.mkdir(exist_ok=True)
    for existing in rules_dir.iterdir():
        if existing.name == "muster.rules" or existing.name.startswith("user-"):
            existing.unlink()
    source_rules = source_home / "rules"
    if source_rules.is_dir():
        for source in source_rules.glob("*.rules"):
            (rules_dir / f"user-{source.name}").symlink_to(source)

    rendered = [
        'prefix_rule(pattern=["gh", "auth", "login"], decision="forbidden")'
    ]
    for rule in codex_rules:
        decision = "allow" if rule.get("decision") == "allow" else "forbidden"
        rendered.append(
            f"prefix_rule(pattern={json.dumps(rule['codex_prefix'])}, decision={json.dumps(decision)})"
        )
    (rules_dir / "muster.rules").write_text("\n".join(rendered) + "\n", encoding="utf-8")
    return overlay


def repair_codex_rollout_path(session_id: str) -> bool:
    """Repair rollout paths left behind by older temporary CODEX_HOME runs.

    Codex keeps the authoritative absolute rollout path in ``state_5.sqlite``.
    Older Muster versions deleted the temporary parent of that path even
    though the same rollout remained available in the user's real sessions
    directory. Repair only that exact thread row when this condition is met.
    """
    source_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    state_db = source_home / "state_5.sqlite"
    if not state_db.is_file():
        return False

    try:
        with sqlite3.connect(state_db, timeout=2) as connection:
            row = connection.execute(
                "SELECT rollout_path FROM threads WHERE id = ?", (session_id,)
            ).fetchone()
            if row is None or not row[0]:
                return False
            current = Path(str(row[0]))
            is_legacy_temp_path = any(
                part.startswith("muster-codex-home-") for part in current.parts
            )
            if current.is_file() and not is_legacy_temp_path:
                return False

            sessions_dir = source_home / "sessions"
            candidates = list(sessions_dir.rglob(f"*{session_id}.jsonl"))
            if len(candidates) != 1:
                return False
            replacement = candidates[0].resolve()
            connection.execute(
                "UPDATE threads SET rollout_path = ? WHERE id = ?",
                (str(replacement), session_id),
            )
            connection.commit()
            return True
    except (OSError, sqlite3.Error):
        # A failed best-effort repair must not prevent Codex from attempting
        # its normal resume path, which may still succeed on newer versions.
        return False
