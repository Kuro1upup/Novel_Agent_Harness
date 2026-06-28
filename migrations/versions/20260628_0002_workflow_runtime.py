"""Add persistent workflow runs, steps and events.

Revision ID: 20260628_0002
Revises: 20260628_0001
Create Date: 2026-06-28
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from novel_harness.storage.orm import Base

revision: str = "20260628_0002"
down_revision: str | None = "20260628_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WORKFLOW_TABLES = {"workflow_runs", "workflow_steps", "workflow_events"}


def upgrade() -> None:
    bind = op.get_bind()
    for table in Base.metadata.sorted_tables:
        if table.name in WORKFLOW_TABLES:
            table.create(bind=bind, checkfirst=False)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(Base.metadata.sorted_tables):
        if table.name in WORKFLOW_TABLES:
            table.drop(bind=bind, checkfirst=False)
