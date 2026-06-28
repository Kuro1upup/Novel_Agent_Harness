"""Add draft lineage, plot selection, and agent telemetry.

Revision ID: 20260629_0004
Revises: 20260628_0003
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260629_0004"
down_revision: str | None = "20260628_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    generation_columns = {column["name"] for column in inspector.get_columns("generation_results")}
    generation_additions = {
        "plot_plan_id": sa.Column("plot_plan_id", sa.String(36), nullable=True),
        "selected_option_id": sa.Column("selected_option_id", sa.String(36), nullable=True),
        "parent_draft_id": sa.Column("parent_draft_id", sa.String(36), nullable=True),
        "revision_number": sa.Column(
            "revision_number", sa.Integer(), nullable=False, server_default="1"
        ),
    }
    for name, column in generation_additions.items():
        if name not in generation_columns:
            op.add_column("generation_results", column)

    generation_foreign_columns = {
        tuple(item.get("constrained_columns") or ())
        for item in inspector.get_foreign_keys("generation_results")
    }
    for name, local, remote_table in (
        ("fk_generation_plot_plan", "plot_plan_id", "plot_plans"),
        ("fk_generation_plot_option", "selected_option_id", "plot_options"),
        ("fk_generation_parent_draft", "parent_draft_id", "generation_results"),
    ):
        if (local,) not in generation_foreign_columns:
            op.create_foreign_key(
                name,
                "generation_results",
                remote_table,
                [local],
                ["id"],
                ondelete="SET NULL",
            )

    agent_columns = {column["name"] for column in inspector.get_columns("agent_runs")}
    agent_additions = {
        "model": sa.Column("model", sa.String(255), nullable=False, server_default=""),
        "prompt_version": sa.Column(
            "prompt_version", sa.String(64), nullable=False, server_default=""
        ),
        "prompt_tokens": sa.Column(
            "prompt_tokens", sa.Integer(), nullable=False, server_default="0"
        ),
        "completion_tokens": sa.Column(
            "completion_tokens", sa.Integer(), nullable=False, server_default="0"
        ),
        "estimated_cost": sa.Column(
            "estimated_cost", sa.Float(), nullable=False, server_default="0"
        ),
        "workflow_run_id": sa.Column("workflow_run_id", sa.String(36), nullable=True),
        "trace_id": sa.Column("trace_id", sa.String(36), nullable=False, server_default=""),
    }
    for name, column in agent_additions.items():
        if name not in agent_columns:
            op.add_column("agent_runs", column)

    agent_foreign_columns = {
        tuple(item.get("constrained_columns") or ())
        for item in inspector.get_foreign_keys("agent_runs")
    }
    if ("workflow_run_id",) not in agent_foreign_columns:
        op.create_foreign_key(
            "fk_agent_run_workflow",
            "agent_runs",
            "workflow_runs",
            ["workflow_run_id"],
            ["id"],
            ondelete="SET NULL",
        )
    agent_indexes = {item["name"] for item in inspector.get_indexes("agent_runs")}
    if "ix_agent_run_trace" not in agent_indexes:
        op.create_index("ix_agent_run_trace", "agent_runs", ["trace_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    agent_indexes = {item["name"] for item in inspector.get_indexes("agent_runs")}
    if "ix_agent_run_trace" in agent_indexes:
        op.drop_index("ix_agent_run_trace", table_name="agent_runs")
    for foreign_key in inspector.get_foreign_keys("agent_runs"):
        if tuple(foreign_key.get("constrained_columns") or ()) == (
            "workflow_run_id",
        ) and foreign_key.get("name"):
            op.drop_constraint(str(foreign_key["name"]), "agent_runs", type_="foreignkey")
    agent_columns = {column["name"] for column in inspector.get_columns("agent_runs")}
    for column in (
        "trace_id",
        "workflow_run_id",
        "estimated_cost",
        "completion_tokens",
        "prompt_tokens",
        "prompt_version",
        "model",
    ):
        if column in agent_columns:
            op.drop_column("agent_runs", column)

    for foreign_key in inspector.get_foreign_keys("generation_results"):
        constrained = tuple(foreign_key.get("constrained_columns") or ())
        if constrained in {
            ("parent_draft_id",),
            ("selected_option_id",),
            ("plot_plan_id",),
        } and foreign_key.get("name"):
            op.drop_constraint(
                str(foreign_key["name"]),
                "generation_results",
                type_="foreignkey",
            )
    generation_columns = {column["name"] for column in inspector.get_columns("generation_results")}
    for column in ("revision_number", "parent_draft_id", "selected_option_id", "plot_plan_id"):
        if column in generation_columns:
            op.drop_column("generation_results", column)
