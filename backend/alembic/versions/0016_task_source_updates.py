"""Link external sources to one task and record unique follow-up updates."""
from alembic import op
import sqlalchemy as sa

revision = "0016_task_source_updates"
down_revision = "0015_recurring_run_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("task_source_links",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_key", sa.String(300), nullable=False),
        sa.UniqueConstraint("project_id", "source_key", name="uq_task_source_link"),
    )
    op.create_table("task_source_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_key", sa.String(300), nullable=False),
        sa.Column("message_id", sa.Uuid(), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.UniqueConstraint("task_id", "event_key", name="uq_task_source_event"),
    )


def downgrade() -> None:
    op.drop_table("task_source_events")
    op.drop_table("task_source_links")
