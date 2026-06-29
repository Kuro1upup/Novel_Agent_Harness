"""Initial MySQL relational metadata schema.

Revision ID: 20260628_0001
Revises:
Create Date: 2026-06-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from novel_harness.storage.orm import Base

revision: str = "20260628_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INITIAL_TABLES = {
    "agent_runs",
    "canon_patches",
    "character_profiles",
    "continuity_issues",
    "document_chunks",
    "documents",
    "fact_risks",
    "generation_results",
    "novel_projects",
    "plot_options",
    "plot_plans",
    "research_notes",
    "search_results",
    "story_bible_versions",
    "story_bibles",
    "style_profiles",
}


def upgrade() -> None:
    """Create tables in foreign-key dependency order."""

    bind = op.get_bind()
    for table in Base.metadata.sorted_tables:
        if table.name not in INITIAL_TABLES:
            continue
        # This migration imports the current ORM metadata so newer optional
        # columns can appear here. Do not create foreign keys to tables that
        # belong to later revisions (for example workflow_runs); those
        # revisions add the constraints after their target tables exist.
        foreign_keys = [
            constraint
            for constraint in table.foreign_key_constraints
            if constraint.referred_table.name in INITIAL_TABLES
        ]
        bind.execute(
            sa.schema.CreateTable(
                table,
                include_foreign_key_constraints=foreign_keys,
            )
        )
        for index in table.indexes:
            index.create(bind=bind, checkfirst=False)


def downgrade() -> None:
    """Drop tables in reverse dependency order."""

    bind = op.get_bind()
    for table in reversed(Base.metadata.sorted_tables):
        if table.name not in INITIAL_TABLES:
            continue
        table.drop(bind=bind, checkfirst=False)
