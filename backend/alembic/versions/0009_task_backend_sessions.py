"""Persist backend session storage outside temporary directories.

Revision ID: 0009_task_backend_sessions
Revises: 0008_project_task_tags
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0009_task_backend_sessions"
down_revision = "0008_project_task_tags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    agent_backend = postgresql.ENUM(
        "claude_code", "codex", name="agent_backend", create_type=False
    )

    op.create_table(
        "task_backend_sessions",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("task_id", uuid_type, nullable=False),
        sa.Column("backend", agent_backend, nullable=False),
        sa.Column("session_id", sa.String(200), nullable=True),
        sa.Column("storage_path", sa.String(1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", name="uq_task_backend_session_task"),
    )

    # Preserve every existing native resume handle. The storage path is
    # deterministic and relative to MUSTER_DATA_DIR, so deployments can move
    # the whole data directory without persisting machine-specific temp paths.
    op.execute(
        """
        INSERT INTO task_backend_sessions
            (id, task_id, backend, session_id, storage_path)
        SELECT
            id,
            id,
            backend,
            session_id,
            'backend-sessions/' || id::text || '/' || backend::text
        FROM tasks
        WHERE session_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_table("task_backend_sessions")
