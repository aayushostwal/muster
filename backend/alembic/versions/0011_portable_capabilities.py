"""Make agents portable and add skill tags.

Revision ID: 0011_portable_capabilities
Revises: 0010_task_runtime_mode
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0011_portable_capabilities"
down_revision = "0010_task_runtime_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "skills",
        sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
    )
    # Preserve legacy values for rollback, but stop requiring runtime-specific
    # defaults on newly created portable profiles.
    agent_backend = postgresql.ENUM(
        "claude_code", "codex", name="agent_backend", create_type=False
    )
    op.alter_column(
        "agent_profiles", "backend", existing_type=agent_backend, nullable=True
    )
    op.alter_column(
        "agent_profiles",
        "thinking_level",
        existing_type=sa.String(length=20),
        nullable=True,
        server_default=None,
    )


def downgrade() -> None:
    agent_backend = postgresql.ENUM(
        "claude_code", "codex", name="agent_backend", create_type=False
    )
    op.execute("UPDATE agent_profiles SET backend = 'claude_code' WHERE backend IS NULL")
    op.execute("UPDATE agent_profiles SET thinking_level = 'medium' WHERE thinking_level IS NULL")
    op.alter_column(
        "agent_profiles",
        "thinking_level",
        existing_type=sa.String(length=20),
        nullable=False,
        server_default="medium",
    )
    op.alter_column(
        "agent_profiles", "backend", existing_type=agent_backend, nullable=False
    )
    op.drop_column("skills", "tags")
