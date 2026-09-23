"""Track capabilities imported from local Claude and Codex environments.

Revision ID: 0003_capability_imports
Revises: 0002_global_registry
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_capability_imports"
down_revision = "0002_global_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    op.create_table(
        "capability_imports",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("resource_type", sa.String(30), nullable=False),
        sa.Column("resource_id", uuid_type, nullable=False),
        sa.Column("source_runtime", sa.String(30), nullable=False),
        sa.Column("source_scope", sa.String(30), nullable=False, server_default="user"),
        sa.Column("source_locator", sa.String(2000), nullable=False),
        sa.Column("source_checksum", sa.String(64), nullable=False),
        sa.Column("source_metadata", sa.JSON(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_runtime",
            "resource_type",
            "source_locator",
            name="uq_capability_import_source",
        ),
    )


def downgrade() -> None:
    op.drop_table("capability_imports")
