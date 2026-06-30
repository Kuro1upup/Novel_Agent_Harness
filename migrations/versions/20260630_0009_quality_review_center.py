"""Add quality review issue status indexes.

Revision ID: 20260630_0009
Revises: 20260629_0008
Create Date: 2026-06-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260630_0009"
down_revision: str | None = "20260629_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    _ensure_status_column(inspector, "continuity_issues")
    _ensure_status_column(inspector, "fact_risks")
    _ensure_status_column(inspector, "memory_conflicts")
    op.execute(sa.text("UPDATE memory_conflicts SET status = 'resolved' WHERE resolved = 1"))
    _ensure_index(
        inspector,
        "continuity_issues",
        "ix_continuity_project_status",
        ["project_id", "status"],
    )
    _ensure_index(
        inspector,
        "continuity_issues",
        "ix_continuity_draft_status",
        ["draft_id", "status"],
    )
    _ensure_index(
        inspector,
        "fact_risks",
        "ix_fact_risk_project_status",
        ["project_id", "status"],
    )
    _ensure_index(
        inspector,
        "fact_risks",
        "ix_fact_risk_draft_status",
        ["draft_id", "status"],
    )
    _ensure_index(
        inspector,
        "memory_conflicts",
        "ix_memory_conflict_project_status",
        ["project_id", "status"],
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table_name, index_name in (
        ("memory_conflicts", "ix_memory_conflict_project_status"),
        ("fact_risks", "ix_fact_risk_draft_status"),
        ("fact_risks", "ix_fact_risk_project_status"),
        ("continuity_issues", "ix_continuity_draft_status"),
        ("continuity_issues", "ix_continuity_project_status"),
    ):
        indexes = {item["name"] for item in inspector.get_indexes(table_name)}
        if index_name in indexes:
            op.drop_index(index_name, table_name=table_name)
    for table_name in ("memory_conflicts", "fact_risks", "continuity_issues"):
        columns = {item["name"] for item in inspector.get_columns(table_name)}
        if "status" in columns:
            op.drop_column(table_name, "status")


def _ensure_status_column(inspector: sa.Inspector, table_name: str) -> None:
    columns = {item["name"] for item in inspector.get_columns(table_name)}
    if "status" not in columns:
        op.add_column(
            table_name,
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default="open",
            ),
        )


def _ensure_index(
    inspector: sa.Inspector,
    table_name: str,
    index_name: str,
    columns: list[str],
) -> None:
    indexes = {item["name"] for item in inspector.get_indexes(table_name)}
    if index_name not in indexes:
        op.create_index(index_name, table_name, columns, unique=False)
