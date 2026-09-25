"""Agent backend adapter protocol and parsed-event types.

See docs/SPEC.md "Process manager" / "Agent backends" sections. Each backend
CLI (claude / codex) is wrapped by a thin adapter that knows how to build the
subprocess command line and how to parse each line of streamed output into a
`ParsedEvent`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Union
import uuid

from app.db.models import AgentBackend, Project, Task


@dataclass(frozen=True, slots=True)
class AgentText:
    """A chunk of assistant-visible text produced by the agent."""

    text: str


@dataclass(frozen=True, slots=True)
class BlockingQuestion:
    """The agent is blocked on a permission/approval decision from the user."""

    text: str


@dataclass(frozen=True, slots=True)
class PermissionRequest:
    """A concrete backend tool call that requires a user decision."""

    tool_name: str
    tool_input: dict = field(default_factory=dict)
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class SessionId:
    """Backend-native session/resume handle, to be stored on Task.session_id."""

    session_id: str


@dataclass(frozen=True, slots=True)
class Done:
    """Clean, successful termination of the current turn."""

    raw: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ErrorEvent:
    """An error surfaced inline in the stream (not necessarily fatal)."""

    message: str


@dataclass(frozen=True, slots=True)
class ActivityEvent:
    """A collapsible execution event such as a tool, diff, log, or sub-agent call."""

    kind: str
    title: str
    content: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class UsageEvent:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0


ParsedEvent = Union[
    AgentText,
    BlockingQuestion,
    PermissionRequest,
    SessionId,
    Done,
    ErrorEvent,
    ActivityEvent,
    UsageEvent,
]


@dataclass(frozen=True, slots=True)
class BackendCommand:
    """A backend invocation and the optional data written to its stdin."""

    argv: list[str]
    stdin_payload: str | None = None


class AgentBackendAdapter(Protocol):
    """Translation layer between Muster's process manager and a backend CLI."""

    backend: AgentBackend

    def build_command(
        self,
        task: Task,
        project: Project,
        bindings: "AdapterBindings",
        secrets: dict[str, str],
        prompt: str | None = None,
    ) -> BackendCommand:
        """Build the argv for the first turn of a task (no prior session)."""
        ...

    def resume_command(
        self,
        task: Task,
        project: Project,
        bindings: "AdapterBindings",
        secrets: dict[str, str],
        session_id: str,
        prompt: str,
    ) -> BackendCommand:
        """Build the argv to continue a task, given its backend session id."""
        ...

    def build_interactive_command(
        self,
        task: Task,
        project: Project,
        bindings: "AdapterBindings",
        secrets: dict[str, str],
        prompt: str | None = None,
    ) -> BackendCommand:
        """Build an argv for the backend's native interactive terminal UI."""
        ...

    def parse_line(self, raw: str) -> ParsedEvent | list[ParsedEvent] | None:
        """Parse one line of the backend's stdout stream into a ParsedEvent."""
        ...


@dataclass(frozen=True, slots=True)
class AdapterBindings:
    """Resolved project bindings needed to build a backend command line.

    Kept separate from the ORM objects so adapters don't need a live DB
    session / lazy-loaded relationships when building commands.
    """

    primary_directory: str | None
    directories: list[str]
    mcp_servers: dict[str, dict]  # name -> {command, args, env}
    tool_rules: list[dict]
    agent_profiles: dict[str, dict]
    skills: dict[str, str]
    selected_agent_prompt: str | None = None
    approval_ids: tuple[uuid.UUID, ...] = ()


def pull_request_guidance(bindings: AdapterBindings) -> str:
    """Keep PR mutations on an authenticated, non-interactive path."""
    has_github_mcp = any(
        "github" in name.casefold()
        or "github" in str(config.get("url", "")).casefold()
        or "github" in str(config.get("command", "")).casefold()
        for name, config in bindings.mcp_servers.items()
    )
    if has_github_mcp:
        return (
            "GitHub operations: a GitHub MCP connector is configured. Use its tools to create "
            "or update pull requests. Never run `gh auth login` or request device authorization."
        )
    return (
        "GitHub operations: no GitHub MCP connector is configured for this project. Do not run "
        "interactive authentication such as `gh auth login`. Complete and push the repository "
        "changes, then clearly report that PR creation or editing requires a GitHub connector "
        "to be enabled in Muster."
    )
