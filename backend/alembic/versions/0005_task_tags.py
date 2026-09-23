"""Add persisted workflow tags to tasks.

Revision ID: 0005_task_tags
Revises: 0004_execution_controls
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_task_tags"
down_revision = "0004_execution_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("tasks", "tags")
