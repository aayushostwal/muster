"""SQLAlchemy models for the Muster data model (see docs/SPEC.md #data-model)."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _uuid_col():
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class AgentBackend(str, enum.Enum):
    claude_code = "claude_code"
    codex = "codex"


class TaskStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    waiting_on_you = "waiting_on_you"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class RuntimeMode(str, enum.Enum):
    structured = "structured"
    interactive = "interactive"


class MessageSender(str, enum.Enum):
    user = "user"
    agent = "agent"
    system = "system"


class AccessScope(str, enum.Enum):
    read = "read"
    read_write = "read_write"


class FailureClass(str, enum.Enum):
    transient = "transient"
    other = "other"


class PrPolicy(str, enum.Enum):
    manual = "manual"
    preferred = "preferred"
    required = "required"


class PrDeliveryStatus(str, enum.Enum):
    awaiting_confirmation = "awaiting_confirmation"
    validating = "validating"
    pushing = "pushing"
    creating_pr = "creating_pr"
    succeeded = "succeeded"
    failed = "failed"
    rejected = "rejected"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = _uuid_col()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_backend: Mapped[AgentBackend] = mapped_column(
        Enum(AgentBackend, name="agent_backend"), default=AgentBackend.claude_code
    )
    default_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    default_context_strategy: Mapped[str] = mapped_column(String(50), default="full")
    primary_directory_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("directory_resources.id", ondelete="SET NULL"), nullable=True
    )
    pr_policy: Mapped[PrPolicy] = mapped_column(
        Enum(PrPolicy, name="pr_policy"), default=PrPolicy.preferred
    )
    pr_provider: Mapped[str] = mapped_column(String(30), default="github")
    pr_remote_name: Mapped[str] = mapped_column(String(100), default="origin")
    pr_branch_prefix: Mapped[str] = mapped_column(String(100), default="muster/")
    pr_base_branch: Mapped[str | None] = mapped_column(String(200), nullable=True)
    pr_validation_command: Mapped[str | None] = mapped_column(Text, nullable=True)
    pr_draft_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    directories: Mapped[list["DirectoryBinding"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    mcp_servers: Mapped[list["McpBinding"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    tools: Mapped[list["ToolBinding"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list["ProjectArtifact"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    tasks: Mapped[list["Task"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    task_tags: Mapped[list["ProjectTaskTag"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectTaskTag.name"
    )
    pr_delivery_runs: Mapped[list["PrDeliveryRun"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    cron_jobs: Mapped[list["CronJob"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    secrets: Mapped[list["Secret"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    capability_overrides: Mapped[list["ProjectCapabilityOverride"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    primary_directory: Mapped["DirectoryResource | None"] = relationship(
        foreign_keys=[primary_directory_id]
    )


class DirectoryBinding(Base):
    __tablename__ = "directory_bindings"
    __table_args__ = (UniqueConstraint("project_id", "path", name="uq_dir_binding"),)

    id: Mapped[uuid.UUID] = _uuid_col()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    directory_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("directory_resources.id", ondelete="CASCADE"), nullable=True
    )
    path: Mapped[str] = mapped_column(String(1000), nullable=False)
    access_scope: Mapped[AccessScope] = mapped_column(Enum(AccessScope, name="access_scope"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="directories")
    directory: Mapped["DirectoryResource | None"] = relationship(back_populates="project_bindings")


class McpBinding(Base):
    __tablename__ = "mcp_bindings"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_mcp_binding"),)

    id: Mapped[uuid.UUID] = _uuid_col()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict)  # command/args/env, schema-validated
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="mcp_servers")


class ToolBinding(Base):
    __tablename__ = "tool_bindings"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_tool_binding"),)

    id: Mapped[uuid.UUID] = _uuid_col()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="tools")


class ProjectTaskTag(Base):
    """Project-scoped tag catalog; task assignments remain in Task.tags for compatibility."""

    __tablename__ = "project_task_tags"
    __table_args__ = (
        UniqueConstraint("project_id", "normalized_name", name="uq_project_task_tag_name"),
    )

    id: Mapped[uuid.UUID] = _uuid_col()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), default="custom")
    color: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped[Project] = relationship(back_populates="task_tags")


class ProjectArtifact(Base):
    __tablename__ = "project_artifacts"

    id: Mapped[uuid.UUID] = _uuid_col()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    local_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    remote_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="artifacts")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = _uuid_col()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    initial_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status"), default=TaskStatus.queued, index=True
    )
    # Only meaningful while status == waiting_on_you; explains *why* the task
    # is waiting so the UI can show a real blocker instead of a guess. One of
    # "blocking_question" (the agent asked something), "tool_permission" (a
    # tool call needs an approval decision), or "awaiting_review" (the turn
    # ended cleanly but there's no verified delivery artifact yet -- see
    # ProcessManager._on_process_exit). Cleared (None) on every other status.
    attention_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    backend: Mapped[AgentBackend] = mapped_column(Enum(AgentBackend, name="agent_backend"))
    runtime_mode: Mapped[RuntimeMode] = mapped_column(
        String(20), default=RuntimeMode.structured, server_default=RuntimeMode.structured.value
    )
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fallback_models: Mapped[list] = mapped_column(JSON, default=list)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    git_baseline_dirty_paths: Mapped[list] = mapped_column(JSON, default=list)
    git_baseline_captured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    thinking_level: Mapped[str] = mapped_column(String(20), default="medium")
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_profiles.id", ondelete="SET NULL"), nullable=True
    )
    context_strategy: Mapped[str] = mapped_column(String(50), default="full")
    session_id: Mapped[str | None] = mapped_column(String(200), nullable=True)  # backend's resume handle
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cron_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cron_jobs.id", ondelete="SET NULL"), nullable=True
    )
    project: Mapped[Project] = relationship(back_populates="tasks")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="Message.created_at"
    )
    context_snapshots: Mapped[list["ContextSnapshot"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    run_attempts: Mapped[list["TaskRunAttempt"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskRunAttempt.created_at"
    )
    invocations: Mapped[list["TaskInvocation"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskInvocation.started_at"
    )
    events: Mapped[list["TaskEvent"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskEvent.created_at"
    )
    tool_approval_requests: Mapped[list["ToolApprovalRequest"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="ToolApprovalRequest.created_at"
    )
    pr_delivery_runs: Mapped[list["PrDeliveryRun"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="PrDeliveryRun.created_at"
    )
    backend_session: Mapped["TaskBackendSession | None"] = relationship(
        back_populates="task", cascade="all, delete-orphan", uselist=False
    )


class DirectoryResource(Base):
    """A globally managed filesystem location that projects may explicitly bind."""

    __tablename__ = "directory_resources"

    id: Mapped[uuid.UUID] = _uuid_col()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    path: Mapped[str] = mapped_column(String(1000), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project_bindings: Mapped[list[DirectoryBinding]] = relationship(
        back_populates="directory", passive_deletes=True
    )


class GlobalMcpServer(Base):
    __tablename__ = "global_mcp_servers"

    id: Mapped[uuid.UUID] = _uuid_col()
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentProfile(Base):
    __tablename__ = "agent_profiles"

    id: Mapped[uuid.UUID] = _uuid_col()
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Legacy runtime defaults are retained as nullable columns so existing
    # installations can roll back without losing data. Muster no longer uses
    # them when selecting or invoking a portable agent profile.
    backend: Mapped[AgentBackend | None] = mapped_column(
        Enum(AgentBackend, name="agent_backend"), nullable=True
    )
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    thinking_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[uuid.UUID] = _uuid_col()
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GlobalTool(Base):
    __tablename__ = "global_tools"

    id: Mapped[uuid.UUID] = _uuid_col()
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CapabilityImport(Base):
    """Provenance for a capability copied from a local agent environment."""

    __tablename__ = "capability_imports"
    __table_args__ = (
        UniqueConstraint(
            "source_runtime",
            "resource_type",
            "source_locator",
            name="uq_capability_import_source",
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_col()
    resource_type: Mapped[str] = mapped_column(String(30), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_runtime: Mapped[str] = mapped_column(String(30), nullable=False)
    source_scope: Mapped[str] = mapped_column(String(30), nullable=False, default="user")
    source_locator: Mapped[str] = mapped_column(String(2000), nullable=False)
    source_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    source_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProjectCapabilityOverride(Base):
    """Project-specific enablement/config for globally available capabilities."""

    __tablename__ = "project_capability_overrides"
    __table_args__ = (
        UniqueConstraint("project_id", "resource_type", "resource_id", name="uq_project_capability"),
    )

    id: Mapped[uuid.UUID] = _uuid_col()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    resource_type: Mapped[str] = mapped_column(String(30), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config_override: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped[Project] = relationship(back_populates="capability_overrides")


class TaskInvocation(Base):
    __tablename__ = "task_invocations"

    id: Mapped[uuid.UUID] = _uuid_col()
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    backend: Mapped[AgentBackend] = mapped_column(Enum(AgentBackend, name="agent_backend"))
    runtime_mode: Mapped[RuntimeMode] = mapped_column(
        String(20), default=RuntimeMode.structured, server_default=RuntimeMode.structured.value
    )
    session_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    thinking_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="running")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped[Task] = relationship(back_populates="invocations")


class TaskBackendSession(Base):
    """Durable backend resume state and its Muster-owned runtime directory."""

    __tablename__ = "task_backend_sessions"

    id: Mapped[uuid.UUID] = _uuid_col()
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), unique=True
    )
    backend: Mapped[AgentBackend] = mapped_column(Enum(AgentBackend, name="agent_backend"))
    session_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    task: Mapped[Task] = relationship(back_populates="backend_session")


class TaskEvent(Base):
    __tablename__ = "task_events"

    id: Mapped[uuid.UUID] = _uuid_col()
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    invocation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("task_invocations.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    task: Mapped[Task] = relationship(back_populates="events")


class ToolApprovalRequest(Base):
    """A backend tool call waiting for an explicit user decision."""

    __tablename__ = "tool_approval_requests"

    id: Mapped[uuid.UUID] = _uuid_col()
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    invocation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("task_invocations.id", ondelete="SET NULL"), nullable=True
    )
    backend: Mapped[AgentBackend] = mapped_column(Enum(AgentBackend, name="agent_backend"))
    tool_name: Mapped[str] = mapped_column(String(200), nullable=False)
    tool_input: Mapped[dict] = mapped_column(JSON, default=dict)
    permission_rule: Mapped[dict] = mapped_column(JSON, default=dict)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    resolution_scope: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped[Task] = relationship(back_populates="tool_approval_requests")


class PrDeliveryRun(Base):
    """Durable state for the explicitly confirmed task-to-PR workflow."""

    __tablename__ = "pr_delivery_runs"

    id: Mapped[uuid.UUID] = _uuid_col()
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    status: Mapped[PrDeliveryStatus] = mapped_column(
        Enum(PrDeliveryStatus, name="pr_delivery_status"),
        default=PrDeliveryStatus.awaiting_confirmation,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(30), default="github")
    repository: Mapped[str | None] = mapped_column(String(300), nullable=True)
    remote_name: Mapped[str] = mapped_column(String(100), default="origin")
    head_branch: Mapped[str | None] = mapped_column(String(300), nullable=True)
    base_branch: Mapped[str | None] = mapped_column(String(300), nullable=True)
    draft: Mapped[bool] = mapped_column(Boolean, default=False)
    file_paths: Mapped[list] = mapped_column(JSON, default=list)
    excluded_paths: Mapped[list] = mapped_column(JSON, default=list)
    commit_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    pr_title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    pr_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_command: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    pr_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pr_state: Mapped[str | None] = mapped_column(String(30), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    completion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped[Task] = relationship(back_populates="pr_delivery_runs")
    project: Mapped[Project] = relationship(back_populates="pr_delivery_runs")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = _uuid_col()
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    sender: Mapped[MessageSender] = mapped_column(Enum(MessageSender, name="message_sender"))
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    media: Mapped[list] = mapped_column(JSON, default=list)  # list of {path, mime, name}
    is_blocking_question: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    task: Mapped[Task] = relationship(back_populates="messages")


class ContextSnapshot(Base):
    __tablename__ = "context_snapshots"

    id: Mapped[uuid.UUID] = _uuid_col()
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    raw_transcript_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    task: Mapped[Task] = relationship(back_populates="context_snapshots")


class CronJob(Base):
    __tablename__ = "cron_jobs"

    id: Mapped[uuid.UUID] = _uuid_col()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    schedule_expr: Mapped[str] = mapped_column(String(100), nullable=False)  # standard 5-field cron
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    backend: Mapped[AgentBackend] = mapped_column(Enum(AgentBackend, name="agent_backend"))
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="cron_jobs")


class TaskRunAttempt(Base):
    """One agent-process attempt for a Task; also mirrored as a system Message."""

    __tablename__ = "task_run_attempts"

    id: Mapped[uuid.UUID] = _uuid_col()
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    failure_class: Mapped[FailureClass | None] = mapped_column(
        Enum(FailureClass, name="failure_class"), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    backoff_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    task: Mapped[Task] = relationship(back_populates="run_attempts")


class Secret(Base):
    """Encrypted-at-rest key/value, scoped to a Project (used by MCP server configs)."""

    __tablename__ = "secrets"
    __table_args__ = (UniqueConstraint("project_id", "key_name", name="uq_secret"),)

    id: Mapped[uuid.UUID] = _uuid_col()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    key_name: Mapped[str] = mapped_column(String(200), nullable=False)
    encrypted_value: Mapped[bytes] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="secrets")
