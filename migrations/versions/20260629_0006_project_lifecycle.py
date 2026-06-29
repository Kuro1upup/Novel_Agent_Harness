"""Add project lifecycle state.

Revision ID: 20260629_0006
Revises: 20260629_0005
Create Date: 2026-06-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260629_0006"
down_revision: str | None = "20260629_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "novel_projects",
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
    )
    op.add_column(
        "novel_projects",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_novel_projects_status",
        "novel_projects",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_novel_projects_status", table_name="novel_projects")
    op.drop_column("novel_projects", "archived_at")
    op.drop_column("novel_projects", "status")
