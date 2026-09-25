"""Add structured/interactive runtime mode to tasks and invocations.

Revision ID: 0010_task_runtime_mode
Revises: 0009_task_backend_sessions
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_task_runtime_mode"
down_revision = "0009_task_backend_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("runtime_mode", sa.String(20), nullable=False, server_default="structured"),
    )
    op.add_column(
        "task_invocations",
        sa.Column("runtime_mode", sa.String(20), nullable=False, server_default="structured"),
    )


def downgrade() -> None:
    op.drop_column("task_invocations", "runtime_mode")
    op.drop_column("tasks", "runtime_mode")
