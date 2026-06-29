"""Associate novel projects with Auth service users.

Revision ID: 20260629_0005
Revises: 20260629_0004
Create Date: 2026-06-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260629_0005"
down_revision: str | None = "20260629_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "novel_projects",
        sa.Column(
            "owner_user_id",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_index(
        "ix_novel_projects_owner_user_id",
        "novel_projects",
        ["owner_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_novel_projects_owner_user_id", table_name="novel_projects")
    op.drop_column("novel_projects", "owner_user_id")
