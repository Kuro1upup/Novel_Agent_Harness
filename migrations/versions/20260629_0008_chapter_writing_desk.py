"""Connect generated drafts to manuscript chapters.

Revision ID: 20260629_0008
Revises: 20260629_0007
Create Date: 2026-06-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260629_0008"
down_revision: str | None = "20260629_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    generation_columns = {item["name"] for item in inspector.get_columns("generation_results")}
    if "chapter_id" not in generation_columns:
        op.add_column(
            "generation_results",
            sa.Column("chapter_id", sa.String(length=36), nullable=True),
        )
    generation_indexes = {item["name"] for item in inspector.get_indexes("generation_results")}
    if "ix_generation_results_chapter_id" not in generation_indexes:
        op.create_index(
            "ix_generation_results_chapter_id",
            "generation_results",
            ["chapter_id"],
            unique=False,
        )

    chapter_columns = {item["name"] for item in inspector.get_columns("manuscript_chapters")}
    if "accepted_draft_id" not in chapter_columns:
        op.add_column(
            "manuscript_chapters",
            sa.Column("accepted_draft_id", sa.String(length=36), nullable=True),
        )
    chapter_foreign_columns = {
        tuple(item.get("constrained_columns") or ())
        for item in inspector.get_foreign_keys("manuscript_chapters")
    }
    if ("accepted_draft_id",) not in chapter_foreign_columns:
        op.create_foreign_key(
            "fk_manuscript_chapter_accepted_draft",
            "manuscript_chapters",
            "generation_results",
            ["accepted_draft_id"],
            ["id"],
            ondelete="SET NULL",
        )
    chapter_unique_columns = {
        tuple(item.get("column_names") or ())
        for item in inspector.get_unique_constraints("manuscript_chapters")
    }
    if ("accepted_draft_id",) not in chapter_unique_columns:
        op.create_unique_constraint(
            "uq_manuscript_chapter_accepted_draft",
            "manuscript_chapters",
            ["accepted_draft_id"],
        )
    op.execute(
        sa.text(
            """
            UPDATE manuscript_chapters
            SET accepted_draft_id = draft_id,
                payload = JSON_SET(payload, '$.accepted_draft_id', draft_id)
            WHERE draft_id IS NOT NULL
              AND status IN ('accepted', 'completed')
            """
        )
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for constraint in inspector.get_unique_constraints("manuscript_chapters"):
        if tuple(constraint.get("column_names") or ()) == ("accepted_draft_id",):
            op.drop_constraint(
                str(constraint["name"]),
                "manuscript_chapters",
                type_="unique",
            )
    for constraint in inspector.get_foreign_keys("manuscript_chapters"):
        if tuple(constraint.get("constrained_columns") or ()) == ("accepted_draft_id",):
            op.drop_constraint(
                str(constraint["name"]),
                "manuscript_chapters",
                type_="foreignkey",
            )
    chapter_columns = {item["name"] for item in inspector.get_columns("manuscript_chapters")}
    if "accepted_draft_id" in chapter_columns:
        op.drop_column("manuscript_chapters", "accepted_draft_id")
    generation_indexes = {item["name"] for item in inspector.get_indexes("generation_results")}
    if "ix_generation_results_chapter_id" in generation_indexes:
        op.drop_index(
            "ix_generation_results_chapter_id",
            table_name="generation_results",
        )
    generation_columns = {item["name"] for item in inspector.get_columns("generation_results")}
    if "chapter_id" in generation_columns:
        op.drop_column("generation_results", "chapter_id")
