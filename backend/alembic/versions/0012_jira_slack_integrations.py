"""Add durable Jira and Slack integration state.

Revision ID: 0012_jira_slack_integrations
Revises: 0011_portable_capabilities
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0012_jira_slack_integrations"
down_revision = "0011_portable_capabilities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("schedule_expr", sa.String(100), nullable=False),
        sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("jira_base_url", sa.String(500)),
        sa.Column("jira_email", sa.String(300)),
        sa.Column("jira_token", sa.LargeBinary()),
        sa.Column("slack_token", sa.LargeBinary()),
        sa.Column("slack_user_id", sa.String(100)),
        sa.Column("slack_jira_project_key", sa.String(30)),
        sa.Column("jira_cursor", sa.DateTime(timezone=True)),
        sa.Column("slack_cursor", sa.DateTime(timezone=True)),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_status", sa.String(30)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "jira_project_mappings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("jira_project_key", sa.String(30), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("jira_project_key", name="uq_jira_project_key"),
    )
    op.create_table(
        "jira_issue_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("issue_id", sa.String(100), nullable=False),
        sa.Column("issue_key", sa.String(100), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("issue_id", name="uq_jira_issue_id"),
    )
    op.create_table(
        "integration_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("external_id", sa.String(300), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("detail", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("source", "external_id", name="uq_integration_event"),
    )
    op.create_table(
        "integration_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("error", sa.Text()),
    )


def downgrade() -> None:
    op.drop_table("integration_runs")
    op.drop_table("integration_events")
    op.drop_table("jira_issue_links")
    op.drop_table("jira_project_mappings")
    op.drop_table("integration_settings")
