"""Persist thinking level on recurring agents."""
from alembic import op
import sqlalchemy as sa

revision = "0014_cron_job_thinking_level"
down_revision = "0013_recurring_agent_intervals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cron_jobs",
        sa.Column("thinking_level", sa.String(20), nullable=False, server_default="medium"),
    )


def downgrade() -> None:
    op.drop_column("cron_jobs", "thinking_level")
