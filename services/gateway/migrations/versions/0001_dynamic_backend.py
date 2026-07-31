"""create dynamic compute and persistent studio tables

Revision ID: 0001_dynamic_backend
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_dynamic_backend"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(128), nullable=False, index=True),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )
    op.create_table(
        "compute_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(128), nullable=False, index=True),
        sa.Column("state", sa.String(32), nullable=False, index=True),
        sa.Column("requested_gpu_count", sa.Integer, nullable=False),
        sa.Column("allocated_gpu_count", sa.Integer, nullable=False),
        sa.Column("selection_mode", sa.String(16), nullable=False),
        sa.Column("profile_policy", sa.String(32), nullable=False),
        sa.Column("allow_partial", sa.Boolean, nullable=False),
        sa.Column("profile_plan_json", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ready_at", sa.DateTime(timezone=True)),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text),
    )
    op.create_table(
        "model_profiles",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("pipeline_spec_json", sa.JSON, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("minimum_gpu_count_policy", sa.Integer, nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "gpu_slots",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("runner_id", sa.String(128)),
        sa.Column("host_id", sa.String(128)),
        sa.Column("gpu_uuid", sa.String(96), nullable=False, unique=True, index=True),
        sa.Column("physical_index", sa.Integer, nullable=False),
        sa.Column("state", sa.String(32), nullable=False, index=True),
        sa.Column("profile_id", sa.String(128)),
        sa.Column("pipeline_spec_hash", sa.String(64)),
        sa.Column(
            "compute_session_id",
            sa.String(64),
            sa.ForeignKey("compute_sessions.id", ondelete="SET NULL"),
            index=True,
        ),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("vram_total_mib", sa.Integer, nullable=False),
        sa.Column("vram_used_mib", sa.Integer, nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text),
    )
    op.create_table(
        "assets",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(128), nullable=False, index=True),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("width", sa.Integer),
        sa.Column("height", sa.Integer),
        sa.Column("source_job_id", sa.String(64), index=True),
        sa.Column("storage_path", sa.Text, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("response_json", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(128), nullable=False, index=True),
        sa.Column(
            "conversation_id",
            sa.String(64),
            sa.ForeignKey("conversations.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("compute_session_id", sa.String(64), nullable=False, index=True),
        sa.Column("state", sa.String(32), nullable=False, index=True),
        sa.Column("progress", sa.Integer, nullable=False),
        sa.Column("current_attempt", sa.Integer, nullable=False),
        sa.Column("profile_id", sa.String(128)),
        sa.Column("result_asset_id", sa.String(64)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("request_json", sa.JSON, nullable=False),
        sa.Column("response_json", sa.JSON, nullable=False),
        sa.Column("manifest_path", sa.Text),
        sa.Column("output_path", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_jobs_owner_created", "jobs", ["owner_id", "created_at"])
    op.create_table(
        "job_attempts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(64),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("slot_id", sa.String(64), nullable=False),
        sa.Column("gpu_uuid", sa.String(96), nullable=False),
        sa.Column("runner_id", sa.String(128)),
        sa.Column("worker_pid", sa.Integer),
        sa.Column("warm_start", sa.Boolean),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("peak_vram_mib", sa.Integer),
        sa.Column("load_seconds", sa.Float),
        sa.Column("generation_seconds", sa.Float),
        sa.Column("encoding_seconds", sa.Float),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("uq_job_attempt", "job_attempts", ["job_id", "attempt"], unique=True)
    op.create_table(
        "job_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.String(128), nullable=False, index=True),
        sa.Column(
            "job_id",
            sa.String(64),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("event_type", sa.String(128), nullable=False, index=True),
        sa.Column("payload_json", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )


def downgrade() -> None:
    for table in (
        "job_events",
        "job_attempts",
        "jobs",
        "assets",
        "gpu_slots",
        "model_profiles",
        "compute_sessions",
        "conversations",
    ):
        op.drop_table(table)
