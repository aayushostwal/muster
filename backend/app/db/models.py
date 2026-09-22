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
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
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
    cron_jobs: Mapped[list["CronJob"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    secrets: Mapped[list["Secret"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class DirectoryBinding(Base):
    __tablename__ = "directory_bindings"
    __table_args__ = (UniqueConstraint("project_id", "path", name="uq_dir_binding"),)

    id: Mapped[uuid.UUID] = _uuid_col()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(String(1000), nullable=False)
    access_scope: Mapped[AccessScope] = mapped_column(Enum(AccessScope, name="access_scope"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="directories")


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
    backend: Mapped[AgentBackend] = mapped_column(Enum(AgentBackend, name="agent_backend"))
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
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
