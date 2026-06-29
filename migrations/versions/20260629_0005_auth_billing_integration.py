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
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("novel_projects")}
    if "owner_user_id" not in columns:
        op.add_column(
            "novel_projects",
            sa.Column(
                "owner_user_id",
                sa.BigInteger(),
                nullable=False,
                server_default="0",
            ),
        )
    indexes = {item["name"] for item in inspector.get_indexes("novel_projects")}
    if "ix_novel_projects_owner_user_id" not in indexes:
        op.create_index(
            "ix_novel_projects_owner_user_id",
            "novel_projects",
            ["owner_user_id"],
            unique=False,
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {item["name"] for item in inspector.get_indexes("novel_projects")}
    if "ix_novel_projects_owner_user_id" in indexes:
        op.drop_index("ix_novel_projects_owner_user_id", table_name="novel_projects")
    columns = {item["name"] for item in inspector.get_columns("novel_projects")}
    if "owner_user_id" in columns:
        op.drop_column("novel_projects", "owner_user_id")
