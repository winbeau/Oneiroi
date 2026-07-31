import hashlib
import json
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from oneiroi_common.compute import (
    ComputeSessionCreate,
    ComputeSessionRelease,
    ComputeSessionSnapshot,
    ComputeSessionState,
    ComputeSlot,
    GpuInfo,
    GpuState,
    ProfileTier,
    ReleasePolicy,
    SelectionMode,
    profile_plan_for_count,
)
from oneiroi_gateway.services.gpu_inventory import GpuInventoryService


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class ComputeBackend(Protocol):
    async def load_slot(
        self,
        session_id: str,
        slot_id: str,
        gpu: GpuInfo,
        profile: ProfileTier,
    ) -> dict[str, object]: ...

    async def release_slot(self, session_id: str, slot: ComputeSlot) -> bool: ...


class UnavailableComputeBackend:
    async def load_slot(
        self,
        session_id: str,
        slot_id: str,
        gpu: GpuInfo,
        profile: ProfileTier,
    ) -> dict[str, object]:
        raise RuntimeError("no Runner control backend is configured")

    async def release_slot(self, session_id: str, slot: ComputeSlot) -> bool:
        return False


class RecordingComputeBackend:
    def __init__(self) -> None:
        self.loaded: list[tuple[str, str, str, ProfileTier]] = []
        self.released: list[tuple[str, str]] = []

    async def load_slot(
        self,
        session_id: str,
        slot_id: str,
        gpu: GpuInfo,
        profile: ProfileTier,
    ) -> dict[str, object]:
        self.loaded.append((session_id, slot_id, gpu.id, profile))
        return {"workerPid": 12345, "loadSeconds": 0.01}

    async def release_slot(self, session_id: str, slot: ComputeSlot) -> bool:
        self.released.append((session_id, slot.id))
        return True


class ComputeSessionService:
    def __init__(self, inventory: GpuInventoryService, backend: ComputeBackend) -> None:
        self.inventory = inventory
        self.backend = backend
        self.sessions: dict[str, ComputeSessionSnapshot] = {}
        self.idempotency: dict[tuple[str, str], tuple[str, str]] = {}

    async def create(
        self,
        owner_id: str,
        payload: ComputeSessionCreate,
        idempotency_key: str | None = None,
    ) -> ComputeSessionSnapshot:
        fingerprint = hashlib.sha256(
            json.dumps(payload.model_dump(mode="json", by_alias=True), sort_keys=True).encode()
        ).hexdigest()
        if idempotency_key:
            existing = self.idempotency.get((owner_id, idempotency_key))
            if existing:
                existing_fingerprint, session_id = existing
                if existing_fingerprint != fingerprint:
                    raise ValueError("IDEMPOTENCY_KEY_REUSED")
                return self.sessions[session_id]

        inventory = await self.inventory.snapshot()
        eligible = [gpu for gpu in inventory.gpus if gpu.eligible]
        if payload.selection_mode is SelectionMode.MANUAL:
            requested_ids = list(dict.fromkeys(payload.gpu_ids))
            available_by_id = {gpu.id: gpu for gpu in eligible}
            if any(gpu_id not in available_by_id for gpu_id in requested_ids):
                raise ValueError("GPU_NOT_ELIGIBLE")
            eligible = [available_by_id[gpu_id] for gpu_id in requested_ids]
        else:
            eligible.sort(
                key=lambda gpu: (
                    gpu.vram_used_mib,
                    gpu.utilization_percent,
                    gpu.temperature_celsius,
                    gpu.id,
                )
            )

        # M2 deliberately proves one safe GPU before M3 expands the allocator to four.
        selected = eligible[: min(payload.requested_gpu_count, 1)]
        if not selected:
            raise RuntimeError("NO_ELIGIBLE_GPU")
        if not payload.allow_partial and len(selected) < payload.requested_gpu_count:
            raise RuntimeError("PARTIAL_ALLOCATION_DISABLED")

        session_id = f"compute-{uuid4().hex[:16]}"
        slots = [
            ComputeSlot(
                id=f"slot-{uuid4().hex[:16]}",
                gpuId=gpu.id,
                physicalIndex=gpu.physical_index,
                state=GpuState.LOADING,
                profile=ProfileTier.FAST,
                loadStage="starting_worker",
                loadProgress=5,
            )
            for gpu in selected
        ]
        session = ComputeSessionSnapshot(
            id=session_id,
            ownerId=owner_id,
            state=ComputeSessionState.LOADING,
            requestedGpuCount=payload.requested_gpu_count,
            allocatedGpuCount=len(selected),
            selectionMode=payload.selection_mode,
            profilePolicy=payload.profile_policy,
            allowPartial=payload.allow_partial,
            profilePlan=profile_plan_for_count(len(selected)),
            slots=slots,
            createdAt=utc_now(),
        )
        self.sessions[session_id] = session
        if idempotency_key:
            self.idempotency[(owner_id, idempotency_key)] = (fingerprint, session_id)

        try:
            for gpu, slot in zip(selected, session.slots, strict=True):
                await self.backend.load_slot(session.id, slot.id, gpu, ProfileTier.FAST)
                slot.state = GpuState.READY
                slot.load_stage = "ready"
                slot.load_progress = 100
            session.state = ComputeSessionState.READY
            session.ready_at = utc_now()
        except Exception as exc:
            for slot in session.slots:
                if slot.state is not GpuState.READY:
                    slot.state = GpuState.ERROR
                    slot.last_error = str(exc)
            session.state = ComputeSessionState.FAILED
            session.error_code = "MODEL_LOAD_FAILED"
            session.error_message = str(exc)
        return session

    def get(self, owner_id: str, session_id: str) -> ComputeSessionSnapshot:
        session = self.sessions.get(session_id)
        if session is None or session.owner_id != owner_id:
            raise KeyError(session_id)
        return session

    async def release(
        self,
        owner_id: str,
        session_id: str,
        payload: ComputeSessionRelease,
    ) -> ComputeSessionSnapshot:
        session = self.get(owner_id, session_id)
        if payload.policy is ReleasePolicy.CANCEL_RUNNING and not payload.confirmed:
            raise ValueError("FORCE_RELEASE_CONFIRMATION_REQUIRED")
        if session.state is ComputeSessionState.RELEASED:
            return session

        session.state = ComputeSessionState.DRAINING
        session.state = ComputeSessionState.RELEASING
        all_released = True
        for slot in session.slots:
            slot.state = GpuState.UNLOADING
            released = await self.backend.release_slot(session.id, slot)
            all_released = all_released and released
            slot.state = GpuState.EMPTY if released else GpuState.ERROR
            if not released:
                slot.last_error = "GPU_MEMORY_NOT_RELEASED"
        if all_released:
            session.state = ComputeSessionState.RELEASED
            session.released_at = utc_now()
        else:
            session.state = ComputeSessionState.FAILED
            session.error_code = "GPU_MEMORY_NOT_RELEASED"
        return session
