"""Add long-term narrative memory and consistency records.

Revision ID: 20260628_0003
Revises: 20260628_0002
Create Date: 2026-06-28
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from novel_harness.storage.orm import Base

revision: str = "20260628_0003"
down_revision: str | None = "20260628_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MEMORY_TABLES = {
    "project_memory_states",
    "memory_records",
    "memory_conflicts",
}


def upgrade() -> None:
    bind = op.get_bind()
    for table in Base.metadata.sorted_tables:
        if table.name in MEMORY_TABLES:
            table.create(bind=bind, checkfirst=False)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(Base.metadata.sorted_tables):
        if table.name in MEMORY_TABLES:
            table.drop(bind=bind, checkfirst=False)
