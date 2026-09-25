"""Add Task.attention_reason for status-derived "needs attention" context.

Revision ID: 0007_task_lifecycle_attention
Revises: 0006_global_tools
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_task_lifecycle_attention"
down_revision = "0006_global_tools"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("attention_reason", sa.String(30), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tasks", "attention_reason")
