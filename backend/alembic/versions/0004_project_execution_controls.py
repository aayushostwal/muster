"""Add project working roots and persisted tool approval requests.

Revision ID: 0004_execution_controls
Revises: 0003_capability_imports
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_execution_controls"
down_revision = "0003_capability_imports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    agent_backend = postgresql.ENUM(
        "claude_code", "codex", name="agent_backend", create_type=False
    )

    op.add_column(
        "projects", sa.Column("primary_directory_id", uuid_type, nullable=True)
    )
    op.create_foreign_key(
        "fk_projects_primary_directory",
        "projects",
        "directory_resources",
        ["primary_directory_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        """
        UPDATE projects AS p
        SET primary_directory_id = candidate.directory_id
        FROM (
            SELECT DISTINCT ON (project_id) project_id, directory_id
            FROM directory_bindings
            WHERE directory_id IS NOT NULL AND access_scope = 'read_write'
            ORDER BY project_id, created_at, id
        ) AS candidate
        WHERE candidate.project_id = p.id
        """
    )

    op.create_table(
        "tool_approval_requests",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("task_id", uuid_type, nullable=False),
        sa.Column("invocation_id", uuid_type, nullable=True),
        sa.Column("backend", agent_backend, nullable=False),
        sa.Column("tool_name", sa.String(200), nullable=False),
        sa.Column("tool_input", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("permission_rule", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("resolution_scope", sa.String(30), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["invocation_id"], ["task_invocations.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tool_approval_requests_status", "tool_approval_requests", ["status"]
    )


def downgrade() -> None:
    op.drop_index("ix_tool_approval_requests_status", table_name="tool_approval_requests")
    op.drop_table("tool_approval_requests")
    op.drop_constraint("fk_projects_primary_directory", "projects", type_="foreignkey")
    op.drop_column("projects", "primary_directory_id")
