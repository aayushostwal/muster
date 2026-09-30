"""Persist source identity and timezone-aware recurring run windows."""
from alembic import op
import sqlalchemy as sa

revision = "0015_recurring_run_controls"
down_revision = "0014_cron_job_thinking_level"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("source_key", sa.String(300), nullable=True))
    op.create_unique_constraint("uq_task_project_source", "tasks", ["project_id", "source_key"])
    op.add_column("cron_jobs", sa.Column("timezone", sa.String(100), nullable=False, server_default="Asia/Kolkata"))
    op.add_column("cron_jobs", sa.Column("window_start", sa.String(5), nullable=True))
    op.add_column("cron_jobs", sa.Column("window_end", sa.String(5), nullable=True))


def downgrade() -> None:
    op.drop_column("cron_jobs", "window_end")
    op.drop_column("cron_jobs", "window_start")
    op.drop_column("cron_jobs", "timezone")
    op.drop_constraint("uq_task_project_source", "tasks", type_="unique")
    op.drop_column("tasks", "source_key")
