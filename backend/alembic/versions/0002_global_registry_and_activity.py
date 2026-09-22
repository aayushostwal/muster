"""Add global capability registry and structured task activity.

Revision ID: 0002_global_registry
Revises: 0001
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_global_registry"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    agent_backend = postgresql.ENUM(
        "claude_code", "codex", name="agent_backend", create_type=False
    )

    op.create_table(
        "directory_resources",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("path", sa.String(1000), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("path"),
    )
    op.create_table(
        "global_mcp_servers",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "agent_profiles",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("backend", agent_backend, nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("thinking_level", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "skills",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "project_capability_overrides",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("project_id", uuid_type, nullable=False),
        sa.Column("resource_type", sa.String(30), nullable=False),
        sa.Column("resource_id", uuid_type, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("config_override", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "resource_type", "resource_id", name="uq_project_capability"),
    )

    op.add_column("directory_bindings", sa.Column("directory_id", uuid_type, nullable=True))
    op.create_foreign_key(
        "fk_directory_bindings_resource",
        "directory_bindings",
        "directory_resources",
        ["directory_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.add_column("tasks", sa.Column("fallback_models", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("tasks", sa.Column("thinking_level", sa.String(20), nullable=False, server_default="medium"))
    op.add_column("tasks", sa.Column("agent_id", uuid_type, nullable=True))
    op.create_foreign_key(
        "fk_tasks_agent_profile", "tasks", "agent_profiles", ["agent_id"], ["id"], ondelete="SET NULL"
    )

    op.create_table(
        "task_invocations",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("task_id", uuid_type, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("backend", agent_backend, nullable=False),
        sa.Column("session_id", sa.String(200), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("thinking_level", sa.String(20), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="running"),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cached_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "task_events",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("task_id", uuid_type, nullable=False),
        sa.Column("invocation_id", uuid_type, nullable=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("event_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["invocation_id"], ["task_invocations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_events_created_at", "task_events", ["created_at"])
    op.drop_column("projects", "archived")


def downgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.drop_index("ix_task_events_created_at", table_name="task_events")
    op.drop_table("task_events")
    op.drop_table("task_invocations")
    op.drop_constraint("fk_tasks_agent_profile", "tasks", type_="foreignkey")
    op.drop_column("tasks", "agent_id")
    op.drop_column("tasks", "thinking_level")
    op.drop_column("tasks", "fallback_models")
    op.drop_constraint("fk_directory_bindings_resource", "directory_bindings", type_="foreignkey")
    op.drop_column("directory_bindings", "directory_id")
    op.drop_table("project_capability_overrides")
    op.drop_table("skills")
    op.drop_table("agent_profiles")
    op.drop_table("global_mcp_servers")
    op.drop_table("directory_resources")
