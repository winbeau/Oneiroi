from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from oneiroi_gateway.db.models.base import Base


class ConversationModel(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ComputeSessionModel(Base):
    __tablename__ = "compute_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    state: Mapped[str] = mapped_column(String(32), index=True)
    requested_gpu_count: Mapped[int] = mapped_column(Integer)
    allocated_gpu_count: Mapped[int] = mapped_column(Integer)
    selection_mode: Mapped[str] = mapped_column(String(16))
    profile_policy: Mapped[str] = mapped_column(String(32))
    allow_partial: Mapped[bool] = mapped_column(Boolean)
    profile_plan_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class GpuSlotModel(Base):
    __tablename__ = "gpu_slots"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    runner_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    host_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    gpu_uuid: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    physical_index: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(32), index=True)
    profile_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pipeline_spec_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    compute_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("compute_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    vram_total_mib: Mapped[int] = mapped_column(Integer)
    vram_used_mib: Mapped[int] = mapped_column(Integer)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ModelProfileModel(Base):
    __tablename__ = "model_profiles"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    version: Mapped[str] = mapped_column(String(64))
    pipeline_spec_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    minimum_gpu_count_policy: Mapped[int] = mapped_column(Integer)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AssetModel(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    type: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(200))
    media_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    storage_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class JobModel(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_owner_created", "owner_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    compute_session_id: Mapped[str] = mapped_column(String(64), index=True)
    state: Mapped[str] = mapped_column(String(32), index=True)
    progress: Mapped[int] = mapped_column(Integer)
    current_attempt: Mapped[int] = mapped_column(Integer)
    profile_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result_asset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    manifest_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class JobAttemptModel(Base):
    __tablename__ = "job_attempts"
    __table_args__ = (Index("uq_job_attempt", "job_id", "attempt", unique=True),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    attempt: Mapped[int] = mapped_column(Integer)
    slot_id: Mapped[str] = mapped_column(String(64))
    gpu_uuid: Mapped[str] = mapped_column(String(96))
    runner_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    worker_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warm_start: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    peak_vram_mib: Mapped[int | None] = mapped_column(Integer, nullable=True)
    load_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    generation_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    encoding_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JobEventModel(Base):
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
