"""Add the PR delivery workflow: project policy/config, task git baseline,
and the pr_delivery_runs state/artifact table.

Revision ID: 0007_pr_delivery
Revises: 0007_task_lifecycle_attention

NOTE: originally branched from 0006_global_tools at the same time as
0007_task_lifecycle_attention (both authored concurrently). Rebased onto it
per that migration's own instructions, since this one landed second.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0007_pr_delivery"
down_revision = "0007_task_lifecycle_attention"
branch_labels = None
depends_on = None


pr_policy_enum = postgresql.ENUM("manual", "preferred", "required", name="pr_policy")
pr_delivery_status_enum = postgresql.ENUM(
    "awaiting_confirmation",
    "validating",
    "pushing",
    "creating_pr",
    "succeeded",
    "failed",
    "rejected",
    name="pr_delivery_status",
)


def upgrade() -> None:
    bind = op.get_bind()
    uuid_type = postgresql.UUID(as_uuid=True)
    pr_policy_enum.create(bind, checkfirst=True)
    pr_delivery_status_enum.create(bind, checkfirst=True)
    pr_policy_enum.create_type = False
    pr_delivery_status_enum.create_type = False

    op.add_column(
        "projects",
        sa.Column("pr_policy", pr_policy_enum, nullable=False, server_default="preferred"),
    )
    op.add_column(
        "projects", sa.Column("pr_provider", sa.String(30), nullable=False, server_default="github")
    )
    op.add_column(
        "projects", sa.Column("pr_remote_name", sa.String(100), nullable=False, server_default="origin")
    )
    op.add_column(
        "projects",
        sa.Column("pr_branch_prefix", sa.String(100), nullable=False, server_default="muster/"),
    )
    op.add_column("projects", sa.Column("pr_base_branch", sa.String(200), nullable=True))
    op.add_column("projects", sa.Column("pr_validation_command", sa.Text(), nullable=True))
    op.add_column(
        "projects",
        sa.Column("pr_draft_default", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.add_column(
        "tasks", sa.Column("git_baseline_dirty_paths", sa.JSON(), nullable=False, server_default="[]")
    )
    op.add_column(
        "tasks", sa.Column("git_baseline_captured_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_table(
        "pr_delivery_runs",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("task_id", uuid_type, nullable=False),
        sa.Column("project_id", uuid_type, nullable=False),
        sa.Column(
            "status",
            pr_delivery_status_enum,
            nullable=False,
            server_default="awaiting_confirmation",
        ),
        sa.Column("provider", sa.String(30), nullable=False, server_default="github"),
        sa.Column("repository", sa.String(300), nullable=True),
        sa.Column("remote_name", sa.String(100), nullable=False, server_default="origin"),
        sa.Column("head_branch", sa.String(300), nullable=True),
        sa.Column("base_branch", sa.String(300), nullable=True),
        sa.Column("draft", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("file_paths", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("excluded_paths", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("commit_message", sa.Text(), nullable=True),
        sa.Column("pr_title", sa.String(300), nullable=True),
        sa.Column("pr_body", sa.Text(), nullable=True),
        sa.Column("validation_command", sa.Text(), nullable=True),
        sa.Column("validation_output", sa.Text(), nullable=True),
        sa.Column("pr_url", sa.String(1000), nullable=True),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("pr_state", sa.String(30), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("completion_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pr_delivery_runs_status", "pr_delivery_runs", ["status"])
    op.create_index("ix_pr_delivery_runs_task_id", "pr_delivery_runs", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_pr_delivery_runs_task_id", table_name="pr_delivery_runs")
    op.drop_index("ix_pr_delivery_runs_status", table_name="pr_delivery_runs")
    op.drop_table("pr_delivery_runs")

    op.drop_column("tasks", "git_baseline_captured_at")
    op.drop_column("tasks", "git_baseline_dirty_paths")

    op.drop_column("projects", "pr_draft_default")
    op.drop_column("projects", "pr_validation_command")
    op.drop_column("projects", "pr_base_branch")
    op.drop_column("projects", "pr_branch_prefix")
    op.drop_column("projects", "pr_remote_name")
    op.drop_column("projects", "pr_provider")
    op.drop_column("projects", "pr_policy")

    bind = op.get_bind()
    pr_delivery_status_enum.drop(bind, checkfirst=True)
    pr_policy_enum.drop(bind, checkfirst=True)
