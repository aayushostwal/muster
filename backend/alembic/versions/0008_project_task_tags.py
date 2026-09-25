"""Add the persisted project task-tag catalog.

Revision ID: 0008_project_task_tags
Revises: 0007_pr_delivery
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0008_project_task_tags"
down_revision = "0007_pr_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_task_tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("normalized_name", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False, server_default="custom"),
        sa.Column("color", sa.String(30), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "normalized_name", name="uq_project_task_tag_name"),
    )


def downgrade() -> None:
    op.drop_table("project_task_tags")
