from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from oneiroi_gateway.db.models.base import Base


class AgentThreadModel(Base):
    __tablename__ = "agent_threads"
    __table_args__ = (
        UniqueConstraint("conversation_id", name="uq_agent_thread_conversation"),
        UniqueConstraint("id", "owner_id", name="uq_agent_threads_id_owner"),
        UniqueConstraint(
            "id",
            "conversation_id",
            "owner_id",
            name="uq_agent_threads_id_conversation_owner",
        ),
        ForeignKeyConstraint(
            ["conversation_id", "owner_id"],
            ["conversations.id", "conversations.owner_id"],
            name="fk_agent_threads_conversation_owner",
            ondelete="CASCADE",
        ),
        Index("ix_agent_threads_owner_updated", "owner_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    conversation_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_cursor: Mapped[int] = mapped_column(Integer, default=0)
    prompt_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AgentRunModel(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("owner_id", "idempotency_key", name="uq_agent_run_idempotency"),
        UniqueConstraint("id", "owner_id", name="uq_agent_runs_id_owner"),
        UniqueConstraint("id", "thread_id", "owner_id", name="uq_agent_runs_id_thread_owner"),
        ForeignKeyConstraint(
            ["thread_id", "conversation_id", "owner_id"],
            [
                "agent_threads.id",
                "agent_threads.conversation_id",
                "agent_threads.owner_id",
            ],
            name="fk_agent_runs_thread_conversation_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["conversation_id", "owner_id"],
            ["conversations.id", "conversations.owner_id"],
            name="fk_agent_runs_conversation_owner",
            ondelete="CASCADE",
        ),
        Index("ix_agent_runs_owner_status", "owner_id", "status"),
        Index("ix_agent_runs_thread_created", "thread_id", "created_at"),
        Index(
            "uq_agent_runs_owner_active",
            "owner_id",
            unique=True,
            postgresql_where=text(
                "status IN ('queued','streaming','waiting_approval','executing_tool',"
                "'cancelling','recovering')"
            ),
            sqlite_where=text(
                "status IN ('queued','streaming','waiting_approval','executing_tool',"
                "'cancelling','recovering')"
            ),
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    conversation_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    model: Mapped[str] = mapped_column(String(200))
    provider: Mapped[str] = mapped_column(String(64))
    transport: Mapped[str] = mapped_column(String(32))
    reasoning_effort: Mapped[str] = mapped_column(String(32))
    prompt_version: Mapped[str] = mapped_column(String(64))
    toolset_version: Mapped[str] = mapped_column(String(64))
    input_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    usage_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    provider_response_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentMessageModel(Base):
    __tablename__ = "agent_messages"
    __table_args__ = (
        UniqueConstraint("thread_id", "sequence", name="uq_agent_message_sequence"),
        ForeignKeyConstraint(
            ["thread_id", "owner_id"],
            ["agent_threads.id", "agent_threads.owner_id"],
            name="fk_agent_messages_thread_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id", "thread_id", "owner_id"],
            ["agent_runs.id", "agent_runs.thread_id", "agent_runs.owner_id"],
            name="fk_agent_messages_run_thread_owner",
            ondelete="CASCADE",
        ),
        Index("ix_agent_messages_owner_thread_sequence", "owner_id", "thread_id", "sequence"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(32))
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), index=True)
    provider_item_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentToolCallModel(Base):
    __tablename__ = "agent_tool_calls"
    __table_args__ = (
        UniqueConstraint("run_id", "provider_call_id", name="uq_agent_provider_call"),
        UniqueConstraint("id", "run_id", "owner_id", name="uq_agent_tool_calls_id_run_owner"),
        ForeignKeyConstraint(
            ["run_id", "owner_id"],
            ["agent_runs.id", "agent_runs.owner_id"],
            name="fk_agent_tool_calls_run_owner",
            ondelete="CASCADE",
        ),
        Index("ix_agent_tool_calls_owner_run", "owner_id", "run_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider_call_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    tool_name: Mapped[str] = mapped_column(String(64))
    tool_version: Mapped[str] = mapped_column(String(32))
    risk: Mapped[str] = mapped_column(String(32))
    arguments_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    arguments_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), index=True)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentApprovalModel(Base):
    __tablename__ = "agent_approvals"
    __table_args__ = (
        UniqueConstraint("tool_call_id", name="uq_agent_approval_tool_call"),
        ForeignKeyConstraint(
            ["run_id", "owner_id"],
            ["agent_runs.id", "agent_runs.owner_id"],
            name="fk_agent_approvals_run_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tool_call_id", "run_id", "owner_id"],
            ["agent_tool_calls.id", "agent_tool_calls.run_id", "agent_tool_calls.owner_id"],
            name="fk_agent_approvals_tool_run_owner",
            ondelete="CASCADE",
        ),
        Index("ix_agent_approvals_owner_run", "owner_id", "run_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    tool_call_id: Mapped[str] = mapped_column(String(64), index=True)
    arguments_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), index=True)
    estimated_cost: Mapped[str | None] = mapped_column(String(128), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class AgentEventModel(Base):
    __tablename__ = "agent_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_agent_event_sequence"),
        ForeignKeyConstraint(
            ["run_id", "thread_id", "owner_id"],
            ["agent_runs.id", "agent_runs.thread_id", "agent_runs.owner_id"],
            name="fk_agent_events_run_thread_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["thread_id", "owner_id"],
            ["agent_threads.id", "agent_threads.owner_id"],
            name="fk_agent_events_thread_owner",
            ondelete="CASCADE",
        ),
        Index("ix_agent_events_owner_run_id", "owner_id", "run_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
