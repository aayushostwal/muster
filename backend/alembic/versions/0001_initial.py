"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


agent_backend_enum = postgresql.ENUM("claude_code", "codex", name="agent_backend")
task_status_enum = postgresql.ENUM(
    "queued", "running", "waiting_on_you", "done", "failed", "cancelled", name="task_status"
)
message_sender_enum = postgresql.ENUM("user", "agent", "system", name="message_sender")
access_scope_enum = postgresql.ENUM("read", "read_write", name="access_scope")
failure_class_enum = postgresql.ENUM("transient", "other", name="failure_class")


def upgrade() -> None:
    bind = op.get_bind()
    agent_backend_enum.create(bind, checkfirst=True)
    task_status_enum.create(bind, checkfirst=True)
    message_sender_enum.create(bind, checkfirst=True)
    access_scope_enum.create(bind, checkfirst=True)
    failure_class_enum.create(bind, checkfirst=True)
    # Each enum type is already created above; reusing the same object as a
    # column type below would otherwise re-issue CREATE TYPE per table.
    for enum_type in (
        agent_backend_enum,
        task_status_enum,
        message_sender_enum,
        access_scope_enum,
        failure_class_enum,
    ):
        enum_type.create_type = False

    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "default_backend",
            agent_backend_enum,
            nullable=False,
            server_default="claude_code",
        ),
        sa.Column("default_model", sa.String(100), nullable=True),
        sa.Column(
            "default_context_strategy", sa.String(50), nullable=False, server_default="full"
        ),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )

    op.create_table(
        "directory_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("path", sa.String(1000), nullable=False),
        sa.Column("access_scope", access_scope_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "path", name="uq_dir_binding"),
    )

    op.create_table(
        "mcp_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "name", name="uq_mcp_binding"),
    )

    op.create_table(
        "tool_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "name", name="uq_tool_binding"),
    )

    op.create_table(
        "project_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("local_path", sa.String(1000), nullable=False),
        sa.Column("remote_url", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "cron_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("schedule_expr", sa.String(100), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("backend", agent_backend_enum, nullable=False),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("initial_prompt", sa.Text(), nullable=False),
        sa.Column(
            "status", task_status_enum, nullable=False, server_default="queued"
        ),
        sa.Column("backend", agent_backend_enum, nullable=False),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("context_strategy", sa.String(50), nullable=False, server_default="full"),
        sa.Column("session_id", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cron_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cron_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_tasks_status", "tasks", ["status"])

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sender", message_sender_enum, nullable=False),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("media", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "is_blocking_question", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index("ix_messages_created_at", "messages", ["created_at"])

    op.create_table(
        "context_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("raw_transcript_path", sa.String(1000), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "task_run_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("failure_class", failure_class_enum, nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("backoff_seconds", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "secrets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key_name", sa.String(200), nullable=False),
        sa.Column("encrypted_value", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "key_name", name="uq_secret"),
    )


def downgrade() -> None:
    op.drop_table("secrets")
    op.drop_table("task_run_attempts")
    op.drop_table("context_snapshots")
    op.drop_index("ix_messages_created_at", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_tasks_status", table_name="tasks")
    op.drop_table("tasks")
    op.drop_table("cron_jobs")
    op.drop_table("project_artifacts")
    op.drop_table("tool_bindings")
    op.drop_table("mcp_bindings")
    op.drop_table("directory_bindings")
    op.drop_table("projects")

    bind = op.get_bind()
    failure_class_enum.drop(bind, checkfirst=True)
    access_scope_enum.drop(bind, checkfirst=True)
    message_sender_enum.drop(bind, checkfirst=True)
    task_status_enum.drop(bind, checkfirst=True)
    agent_backend_enum.drop(bind, checkfirst=True)
