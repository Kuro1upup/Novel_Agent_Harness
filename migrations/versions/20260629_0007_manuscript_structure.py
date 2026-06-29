"""Add ordered manuscript volumes and chapters.

Revision ID: 20260629_0007
Revises: 20260629_0006
Create Date: 2026-06-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260629_0007"
down_revision: str | None = "20260629_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "manuscript_volumes",
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["novel_projects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_manuscript_volume_project_position",
        "manuscript_volumes",
        ["project_id", "position"],
        unique=False,
    )
    op.create_index(
        "ix_manuscript_volume_project_status",
        "manuscript_volumes",
        ["project_id", "status"],
        unique=False,
    )

    op.create_table(
        "manuscript_chapters",
        sa.Column("volume_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("draft_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["draft_id"],
            ["generation_results.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["novel_projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["volume_id"],
            ["manuscript_volumes.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_id"),
    )
    op.create_index(
        "ix_manuscript_chapter_project_status",
        "manuscript_chapters",
        ["project_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_manuscript_chapter_volume_position",
        "manuscript_chapters",
        ["project_id", "volume_id", "position"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_manuscript_chapter_volume_position",
        table_name="manuscript_chapters",
    )
    op.drop_index(
        "ix_manuscript_chapter_project_status",
        table_name="manuscript_chapters",
    )
    op.drop_table("manuscript_chapters")
    op.drop_index(
        "ix_manuscript_volume_project_status",
        table_name="manuscript_volumes",
    )
    op.drop_index(
        "ix_manuscript_volume_project_position",
        table_name="manuscript_volumes",
    )
    op.drop_table("manuscript_volumes")
