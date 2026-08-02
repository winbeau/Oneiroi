"""add cumulative Agent run budgets

Revision ID: 0004_agent_run_budgets
Revises: 0003_agent_execution_lease
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_agent_run_budgets"
down_revision = "0003_agent_execution_lease"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("active_duration_seconds", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "agent_runs",
        sa.Column("provider_event_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "provider_event_count")
    op.drop_column("agent_runs", "active_duration_seconds")
