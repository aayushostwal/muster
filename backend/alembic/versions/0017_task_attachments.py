"""Persist files and images attached when a task is created."""
from alembic import op
import sqlalchemy as sa

revision = "0017_task_attachments"
down_revision = "0016_task_source_updates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("media", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("tasks", "media")
