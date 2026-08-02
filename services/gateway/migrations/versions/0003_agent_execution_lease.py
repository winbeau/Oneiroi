"""add Agent execution leases

Revision ID: 0003_agent_execution_lease
Revises: 0002_agent_runtime
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_agent_execution_lease"
down_revision = "0002_agent_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("executor_id", sa.String(128), nullable=True))
    op.add_column(
        "agent_runs",
        sa.Column("execution_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agent_runs_executor_id", "agent_runs", ["executor_id"])
    op.create_index(
        "ix_agent_runs_execution_lease_expires_at",
        "agent_runs",
        ["execution_lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_runs_execution_lease_expires_at", table_name="agent_runs")
    op.drop_index("ix_agent_runs_executor_id", table_name="agent_runs")
    op.drop_column("agent_runs", "execution_lease_expires_at")
    op.drop_column("agent_runs", "executor_id")
