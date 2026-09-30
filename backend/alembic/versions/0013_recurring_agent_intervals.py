"""Allow recurring agents to run at a chosen interval."""
from alembic import op
import sqlalchemy as sa

revision = "0013_recurring_agent_intervals"
down_revision = "0012_jira_slack_integrations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cron_jobs", sa.Column("interval_minutes", sa.Integer(), nullable=True))
    op.create_check_constraint("ck_cron_jobs_interval_minutes_positive", "cron_jobs", "interval_minutes IS NULL OR interval_minutes > 0")


def downgrade() -> None:
    op.drop_constraint("ck_cron_jobs_interval_minutes_positive", "cron_jobs", type_="check")
    op.drop_column("cron_jobs", "interval_minutes")
