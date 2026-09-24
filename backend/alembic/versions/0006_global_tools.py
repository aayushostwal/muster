"""Add global tool registry and safe defaults.

Revision ID: 0006_global_tools
Revises: 0005_task_tags
"""

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_global_tools"
down_revision = "0005_task_tags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    table = op.create_table(
        "global_tools",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    defaults = [
        ("Read files", "Read workspace files without asking.", "claude_code", "Read", []),
        ("Search files", "Search file contents across the workspace.", "all", "Grep", ["rg"]),
        ("Discover files", "Find files and folders by pattern.", "claude_code", "Glob", []),
        ("Edit files", "Apply focused edits inside approved directories.", "claude_code", "Edit", []),
        ("Write files", "Create files inside approved directories.", "claude_code", "Write", []),
        ("Sandboxed shell", "Run shell commands in Codex's workspace-write sandbox.", "codex", None, ["bash"]),
        ("Git status", "Inspect repository state without changing it.", "all", "Bash(git status *)", ["git", "status"]),
        ("Git diff", "Review working-tree changes without changing them.", "all", "Bash(git diff *)", ["git", "diff"]),
        ("Git log", "Inspect commit history without changing it.", "all", "Bash(git log *)", ["git", "log"]),
        ("Web fetch", "Read public documentation and web resources.", "claude_code", "WebFetch", []),
    ]
    op.bulk_insert(
        table,
        [
            {
                "id": uuid.uuid5(uuid.NAMESPACE_URL, f"muster:global-tool:{name}"),
                "name": name,
                "description": description,
                "config": {
                    "backend": backend,
                    "decision": "allow",
                    "claude_pattern": claude_pattern,
                    "codex_prefix": codex_prefix,
                },
                "enabled": True,
            }
            for name, description, backend, claude_pattern, codex_prefix in defaults
        ],
    )


def downgrade() -> None:
    op.drop_table("global_tools")
