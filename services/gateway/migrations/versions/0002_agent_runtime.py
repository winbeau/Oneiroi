"""create durable Agent runtime tables

Revision ID: 0002_agent_runtime
Revises: 0001_dynamic_backend
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_agent_runtime"
down_revision = "0001_dynamic_backend"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_conversations_id_owner", "conversations", ["id", "owner_id"])
    op.create_table(
        "agent_threads",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("conversation_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("summary_text", sa.Text),
        sa.Column("summary_cursor", sa.Integer, nullable=False, server_default="0"),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("conversation_id", name="uq_agent_thread_conversation"),
        sa.UniqueConstraint("id", "owner_id", name="uq_agent_threads_id_owner"),
        sa.UniqueConstraint(
            "id",
            "conversation_id",
            "owner_id",
            name="uq_agent_threads_id_conversation_owner",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "owner_id"],
            ["conversations.id", "conversations.owner_id"],
            name="fk_agent_threads_conversation_owner",
            ondelete="CASCADE",
        ),
    )
    for name, columns in (
        ("ix_agent_threads_owner_id", ["owner_id"]),
        ("ix_agent_threads_conversation_id", ["conversation_id"]),
        ("ix_agent_threads_status", ["status"]),
        ("ix_agent_threads_updated_at", ["updated_at"]),
        ("ix_agent_threads_owner_updated", ["owner_id", "updated_at"]),
    ):
        op.create_index(name, "agent_threads", columns)

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("thread_id", sa.String(64), nullable=False),
        sa.Column("conversation_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("transport", sa.String(32), nullable=False),
        sa.Column("reasoning_effort", sa.String(32), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("toolset_version", sa.String(64), nullable=False),
        sa.Column("input_snapshot_json", sa.JSON, nullable=False),
        sa.Column("usage_json", sa.JSON, nullable=False),
        sa.Column("provider_response_id", sa.String(128)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text),
        sa.Column("output_message_id", sa.String(64)),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("owner_id", "idempotency_key", name="uq_agent_run_idempotency"),
        sa.UniqueConstraint("id", "owner_id", name="uq_agent_runs_id_owner"),
        sa.UniqueConstraint("id", "thread_id", "owner_id", name="uq_agent_runs_id_thread_owner"),
        sa.ForeignKeyConstraint(
            ["thread_id", "conversation_id", "owner_id"],
            [
                "agent_threads.id",
                "agent_threads.conversation_id",
                "agent_threads.owner_id",
            ],
            name="fk_agent_runs_thread_conversation_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "owner_id"],
            ["conversations.id", "conversations.owner_id"],
            name="fk_agent_runs_conversation_owner",
            ondelete="CASCADE",
        ),
    )
    for name, columns in (
        ("ix_agent_runs_owner_id", ["owner_id"]),
        ("ix_agent_runs_thread_id", ["thread_id"]),
        ("ix_agent_runs_conversation_id", ["conversation_id"]),
        ("ix_agent_runs_status", ["status"]),
        ("ix_agent_runs_owner_status", ["owner_id", "status"]),
        ("ix_agent_runs_thread_created", ["thread_id", "created_at"]),
    ):
        op.create_index(name, "agent_runs", columns)
    op.create_index(
        "uq_agent_runs_owner_active",
        "agent_runs",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('queued','streaming','waiting_approval','executing_tool',"
            "'cancelling','recovering')"
        ),
        sqlite_where=sa.text(
            "status IN ('queued','streaming','waiting_approval','executing_tool',"
            "'cancelling','recovering')"
        ),
    )

    op.create_table(
        "agent_messages",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("thread_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64)),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("content_json", sa.JSON, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("provider_item_id", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("thread_id", "sequence", name="uq_agent_message_sequence"),
        sa.ForeignKeyConstraint(
            ["thread_id", "owner_id"],
            ["agent_threads.id", "agent_threads.owner_id"],
            name="fk_agent_messages_thread_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "thread_id", "owner_id"],
            ["agent_runs.id", "agent_runs.thread_id", "agent_runs.owner_id"],
            name="fk_agent_messages_run_thread_owner",
            ondelete="CASCADE",
        ),
    )
    for name, columns in (
        ("ix_agent_messages_owner_id", ["owner_id"]),
        ("ix_agent_messages_thread_id", ["thread_id"]),
        ("ix_agent_messages_run_id", ["run_id"]),
        ("ix_agent_messages_status", ["status"]),
        (
            "ix_agent_messages_owner_thread_sequence",
            ["owner_id", "thread_id", "sequence"],
        ),
    ):
        op.create_index(name, "agent_messages", columns)

    op.create_table(
        "agent_tool_calls",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("provider_call_id", sa.String(128)),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("tool_name", sa.String(64), nullable=False),
        sa.Column("tool_version", sa.String(32), nullable=False),
        sa.Column("risk", sa.String(32), nullable=False),
        sa.Column("arguments_json", sa.JSON, nullable=False),
        sa.Column("arguments_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("result_json", sa.JSON),
        sa.Column("resource_type", sa.String(32)),
        sa.Column("resource_id", sa.String(64)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("run_id", "provider_call_id", name="uq_agent_provider_call"),
        sa.UniqueConstraint("id", "run_id", "owner_id", name="uq_agent_tool_calls_id_run_owner"),
        sa.ForeignKeyConstraint(
            ["run_id", "owner_id"],
            ["agent_runs.id", "agent_runs.owner_id"],
            name="fk_agent_tool_calls_run_owner",
            ondelete="CASCADE",
        ),
    )
    for name, columns in (
        ("ix_agent_tool_calls_owner_id", ["owner_id"]),
        ("ix_agent_tool_calls_run_id", ["run_id"]),
        ("ix_agent_tool_calls_status", ["status"]),
        ("ix_agent_tool_calls_owner_run", ["owner_id", "run_id"]),
    ):
        op.create_index(name, "agent_tool_calls", columns)

    op.create_table(
        "agent_approvals",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("tool_call_id", sa.String(64), nullable=False),
        sa.Column("arguments_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("estimated_cost", sa.String(128)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("decision_metadata_json", sa.JSON, nullable=False),
        sa.UniqueConstraint("tool_call_id", name="uq_agent_approval_tool_call"),
        sa.ForeignKeyConstraint(
            ["run_id", "owner_id"],
            ["agent_runs.id", "agent_runs.owner_id"],
            name="fk_agent_approvals_run_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tool_call_id", "run_id", "owner_id"],
            ["agent_tool_calls.id", "agent_tool_calls.run_id", "agent_tool_calls.owner_id"],
            name="fk_agent_approvals_tool_run_owner",
            ondelete="CASCADE",
        ),
    )
    for name, columns in (
        ("ix_agent_approvals_owner_id", ["owner_id"]),
        ("ix_agent_approvals_run_id", ["run_id"]),
        ("ix_agent_approvals_tool_call_id", ["tool_call_id"]),
        ("ix_agent_approvals_status", ["status"]),
        ("ix_agent_approvals_expires_at", ["expires_at"]),
        ("ix_agent_approvals_owner_run", ["owner_id", "run_id"]),
    ):
        op.create_index(name, "agent_approvals", columns)

    op.create_table(
        "agent_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("thread_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("payload_json", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "sequence", name="uq_agent_event_sequence"),
        sa.ForeignKeyConstraint(
            ["run_id", "thread_id", "owner_id"],
            ["agent_runs.id", "agent_runs.thread_id", "agent_runs.owner_id"],
            name="fk_agent_events_run_thread_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["thread_id", "owner_id"],
            ["agent_threads.id", "agent_threads.owner_id"],
            name="fk_agent_events_thread_owner",
            ondelete="CASCADE",
        ),
    )
    for name, columns in (
        ("ix_agent_events_owner_id", ["owner_id"]),
        ("ix_agent_events_run_id", ["run_id"]),
        ("ix_agent_events_thread_id", ["thread_id"]),
        ("ix_agent_events_event_type", ["event_type"]),
        ("ix_agent_events_created_at", ["created_at"]),
        ("ix_agent_events_owner_run_id", ["owner_id", "run_id", "id"]),
    ):
        op.create_index(name, "agent_events", columns)


def downgrade() -> None:
    for table in (
        "agent_events",
        "agent_approvals",
        "agent_tool_calls",
        "agent_messages",
        "agent_runs",
        "agent_threads",
    ):
        op.drop_table(table)
    op.execute("ALTER TABLE conversations DROP CONSTRAINT IF EXISTS uq_conversations_id_owner")
