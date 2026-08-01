import asyncio
import hashlib
import json
import time
from contextlib import suppress
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
    allocated_gpu_count,
    profile_plan_for_count,
)
from oneiroi_gateway.redis.leases import InMemoryLeaseStore, LeaseStore
from oneiroi_gateway.repositories.compute import ComputeStateRepository
from oneiroi_gateway.services.gpu_inventory import GpuInventoryService
from oneiroi_gateway.services.session_events import SessionEventService


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class ComputeBackend(Protocol):
    async def load_slot(
        self,
        session_id: str,
        slot_id: str,
        gpu: GpuInfo,
        profile: ProfileTier,
        fencing_token: str,
    ) -> dict[str, object]: ...

    async def release_slot(
        self,
        session_id: str,
        slot: ComputeSlot,
        fencing_token: str,
    ) -> bool: ...


class UnavailableComputeBackend:
    async def load_slot(
        self,
        session_id: str,
        slot_id: str,
        gpu: GpuInfo,
        profile: ProfileTier,
        fencing_token: str,
    ) -> dict[str, object]:
        raise RuntimeError("no Runner control backend is configured")

    async def release_slot(
        self,
        session_id: str,
        slot: ComputeSlot,
        fencing_token: str,
    ) -> bool:
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
        fencing_token: str,
    ) -> dict[str, object]:
        self.loaded.append((session_id, slot_id, gpu.id, profile))
        return {"workerPid": 12345, "loadSeconds": 0.01}

    async def release_slot(
        self,
        session_id: str,
        slot: ComputeSlot,
        fencing_token: str,
    ) -> bool:
        self.released.append((session_id, slot.id))
        return True


class ComputeSessionService:
    def __init__(
        self,
        inventory: GpuInventoryService,
        backend: ComputeBackend,
        *,
        leases: LeaseStore | None = None,
        events: SessionEventService | None = None,
        state_repository: ComputeStateRepository | None = None,
        lease_ttl_seconds: float = 60,
        idle_ttl_seconds: float = 86_400,
    ) -> None:
        self.inventory = inventory
        self.backend = backend
        self.leases = leases or InMemoryLeaseStore()
        self.events = events or SessionEventService()
        self.state_repository = state_repository
        self.lease_ttl_seconds = lease_ttl_seconds
        self.idle_ttl_seconds = idle_ttl_seconds
        self.sessions: dict[str, ComputeSessionSnapshot] = {}
        self.idempotency: dict[tuple[str, str], tuple[str, str]] = {}
        self._lease_tasks: dict[str, asyncio.Task[None]] = {}
        self._fencing_tokens: dict[str, str] = {}
        self._last_activity: dict[str, float] = {}

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
            if not requested_ids:
                raise ValueError("MANUAL_GPU_IDS_REQUIRED")
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

        requested = payload.requested_gpu_count
        expected = allocated_gpu_count(requested, len(eligible), payload.allow_partial)
        if expected == 0:
            reason = "NO_ELIGIBLE_GPU" if not eligible else "PARTIAL_ALLOCATION_DISABLED"
            raise RuntimeError(reason)

        session_id = f"compute-{uuid4().hex[:16]}"
        acquired = await self.leases.acquire(
            [gpu.id for gpu in eligible],
            requested,
            session_id,
            ttl_seconds=self.lease_ttl_seconds,
            allow_partial=payload.allow_partial,
        )
        if not acquired:
            raise RuntimeError("NO_ELIGIBLE_GPU")
        acquired_ids = {lease.gpu_id for lease in acquired}
        fencing_by_gpu = {lease.gpu_id: lease.fencing_token for lease in acquired}
        selected = [gpu for gpu in eligible if gpu.id in acquired_ids]
        if not payload.allow_partial and len(selected) < requested:
            await self.leases.release_session(session_id)
            raise RuntimeError("PARTIAL_ALLOCATION_DISABLED")

        plan = profile_plan_for_count(len(selected))
        profiles = [ProfileTier.FAST] * plan.fast + [ProfileTier.HQ] * plan.hq
        slots = [
            ComputeSlot(
                id=f"slot-{uuid4().hex[:16]}",
                gpuId=gpu.id,
                physicalIndex=gpu.physical_index,
                state=GpuState.RESERVED,
                profile=profile,
                loadStage="reserving_gpu",
                loadProgress=0,
            )
            for gpu, profile in zip(selected, profiles, strict=True)
        ]
        session = ComputeSessionSnapshot(
            id=session_id,
            ownerId=owner_id,
            state=ComputeSessionState.ALLOCATING,
            requestedGpuCount=requested,
            allocatedGpuCount=len(selected),
            selectionMode=payload.selection_mode,
            profilePolicy=payload.profile_policy,
            allowPartial=payload.allow_partial,
            profilePlan=plan,
            slots=slots,
            createdAt=utc_now(),
        )
        self.sessions[session_id] = session
        self._last_activity[session_id] = time.monotonic()
        self._fencing_tokens.update(
            {slot.id: fencing_by_gpu[slot.gpu_id] for slot in session.slots}
        )
        if idempotency_key:
            self.idempotency[(owner_id, idempotency_key)] = (fingerprint, session_id)
        await self._emit_snapshot(session, "compute.session.updated")
        self._start_lease_renewal(session)

        failures = 0
        session.state = ComputeSessionState.LOADING
        for gpu, slot in zip(selected, session.slots, strict=True):
            slot.state = GpuState.LOADING
            slot.load_stage = "starting_worker"
            slot.load_progress = 5
            await self._emit_slot(session, slot)
            try:
                result = await self.backend.load_slot(
                    session.id,
                    slot.id,
                    gpu,
                    slot.profile or ProfileTier.FAST,
                    self._fencing_tokens[slot.id],
                )
                slot.state = GpuState.READY
                slot.load_stage = "ready"
                slot.load_progress = 100
                if pipeline_hash := result.get("pipelineSpecHash"):
                    slot.pipeline_spec_hash = str(pipeline_hash)
            except Exception as exc:
                failures += 1
                slot.state = GpuState.ERROR
                slot.last_error = str(exc)
                await self.leases.release_gpu(slot.gpu_id, session.id)
                self._fencing_tokens.pop(slot.id, None)
            await self._emit_slot(session, slot)

        ready_count = sum(slot.state is GpuState.READY for slot in session.slots)
        if ready_count == len(session.slots) and len(session.slots) == requested:
            session.state = ComputeSessionState.READY
            session.ready_at = utc_now()
            await self._emit_snapshot(session, "compute.session.ready")
        elif ready_count:
            session.state = ComputeSessionState.DEGRADED
            session.ready_at = utc_now()
            session.error_code = "PARTIAL_ALLOCATION" if not failures else "MODEL_LOAD_FAILED"
            await self._emit_snapshot(session, "compute.session.degraded")
        else:
            session.state = ComputeSessionState.FAILED
            session.error_code = "MODEL_LOAD_FAILED"
            session.error_message = "no allocated slot became ready"
            await self.leases.release_session(session.id)
            await self._stop_lease_renewal(session.id)
            await self._emit_snapshot(session, "compute.session.failed")
        return session

    async def restore(self) -> list[str]:
        if self.state_repository is None:
            return []
        active_leases = await self.leases.active()
        restored: list[str] = []
        for session in await self.state_repository.load_active():
            self.sessions[session.id] = session
            self._last_activity[session.id] = time.monotonic()
            for slot in session.slots:
                lease = active_leases.get(slot.gpu_id)
                if lease is not None and lease.session_id == session.id:
                    self._fencing_tokens[slot.id] = lease.fencing_token
                elif slot.state not in {GpuState.EMPTY, GpuState.ERROR}:
                    slot.state = GpuState.ERROR
                    slot.last_error = "GPU_LEASE_LOST"
                    session.state = ComputeSessionState.FAILED
                    session.error_code = "GPU_LEASE_LOST"
            if self._fencing_tokens_for_session(session):
                self._start_lease_renewal(session)
            await self.state_repository.save(session)
            restored.append(session.id)
        return restored

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
        await self._emit_snapshot(session, "compute.session.updated")
        session.state = ComputeSessionState.RELEASING
        all_released = True
        for slot in session.slots:
            slot.state = GpuState.UNLOADING
            await self._emit_slot(session, slot)
            released = await self.backend.release_slot(
                session.id,
                slot,
                self._fencing_tokens.get(slot.id, ""),
            )
            all_released = all_released and released
            slot.state = GpuState.EMPTY if released else GpuState.ERROR
            if not released:
                slot.last_error = "GPU_MEMORY_NOT_RELEASED"
            await self._emit_slot(session, slot)
        if all_released:
            await self.leases.release_session(session.id)
            for slot in session.slots:
                self._fencing_tokens.pop(slot.id, None)
            await self._stop_lease_renewal(session.id)
            session.state = ComputeSessionState.RELEASED
            session.released_at = utc_now()
            self._last_activity.pop(session.id, None)
            await self._emit_snapshot(session, "compute.session.released")
        else:
            session.state = ComputeSessionState.FAILED
            session.error_code = "GPU_MEMORY_NOT_RELEASED"
            await self._emit_snapshot(session, "compute.session.failed")
        return session

    async def reconcile_stale_gpus(self, stale_gpu_ids: set[str]) -> list[str]:
        affected: list[str] = []
        for session in self.sessions.values():
            changed = False
            for slot in session.slots:
                if slot.gpu_id not in stale_gpu_ids or slot.state in {
                    GpuState.EMPTY,
                    GpuState.ERROR,
                }:
                    continue
                slot.state = GpuState.ERROR
                slot.last_error = "RUNNER_HEARTBEAT_LOST"
                await self.leases.release_gpu(slot.gpu_id, session.id)
                self._fencing_tokens.pop(slot.id, None)
                await self._emit_slot(session, slot)
                changed = True
            if changed:
                affected.append(session.id)
                if any(slot.state is GpuState.READY for slot in session.slots):
                    session.state = ComputeSessionState.DEGRADED
                    session.error_code = "RUNNER_HEARTBEAT_LOST"
                    await self._emit_snapshot(session, "compute.session.degraded")
                else:
                    session.state = ComputeSessionState.FAILED
                    session.error_code = "RUNNER_HEARTBEAT_LOST"
                    await self._emit_snapshot(session, "compute.session.failed")
        return affected

    def _fencing_tokens_for_session(self, session: ComputeSessionSnapshot) -> list[str]:
        return [
            self._fencing_tokens[slot.id]
            for slot in session.slots
            if slot.id in self._fencing_tokens
        ]

    async def persist(self, session_id: str) -> None:
        if self.state_repository is not None and session_id in self.sessions:
            await self.state_repository.save(self.sessions[session_id])

    def touch(self, session_id: str) -> None:
        if session_id in self.sessions:
            self._last_activity[session_id] = time.monotonic()

    def fencing_token(self, slot_id: str) -> str:
        try:
            return self._fencing_tokens[slot_id]
        except KeyError as exc:
            raise RuntimeError("GPU_LEASE_LOST") from exc

    async def close(self) -> None:
        for session_id in list(self._lease_tasks):
            await self._stop_lease_renewal(session_id)
        close = getattr(self.leases, "close", None)
        if close is not None:
            await close()

    def _start_lease_renewal(self, session: ComputeSessionSnapshot) -> None:
        task = asyncio.create_task(
            self._renew_lease_loop(session),
            name=f"lease-renewal-{session.id}",
        )
        self._lease_tasks[session.id] = task

    async def _stop_lease_renewal(self, session_id: str) -> None:
        task = self._lease_tasks.pop(session_id, None)
        if task is None or task is asyncio.current_task():
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _renew_lease_loop(self, session: ComputeSessionSnapshot) -> None:
        interval = max(0.01, self.lease_ttl_seconds / 3)
        try:
            while session.state is not ComputeSessionState.RELEASED:
                await asyncio.sleep(interval)
                last_activity = self._last_activity.get(session.id, time.monotonic())
                if (
                    session.state in {ComputeSessionState.READY, ComputeSessionState.DEGRADED}
                    and time.monotonic() - last_activity >= self.idle_ttl_seconds
                ):
                    await self.release(
                        session.owner_id,
                        session.id,
                        ComputeSessionRelease(),
                    )
                    return
                expected = {
                    slot.gpu_id
                    for slot in session.slots
                    if slot.state is not GpuState.EMPTY
                    and (
                        slot.state is not GpuState.ERROR
                        or slot.last_error == "GPU_MEMORY_NOT_RELEASED"
                    )
                }
                if not expected:
                    return
                try:
                    renewed = set(
                        await self.leases.renew_session(
                            session.id,
                            ttl_seconds=self.lease_ttl_seconds,
                        )
                    )
                except Exception:
                    session.state = ComputeSessionState.FAILED
                    session.error_code = "REDIS_LEASE_RENEWAL_FAILED"
                    session.error_message = "GPU lease renewal backend is unavailable"
                    await self._emit_snapshot(session, "compute.session.failed")
                    return
                missing = expected - renewed
                if not missing:
                    continue
                for slot in session.slots:
                    if slot.gpu_id in missing:
                        slot.state = GpuState.ERROR
                        slot.last_error = "GPU_LEASE_LOST"
                        await self._emit_slot(session, slot)
                session.state = ComputeSessionState.FAILED
                session.error_code = "GPU_LEASE_LOST"
                session.error_message = "one or more GPU leases could not be renewed"
                await self._emit_snapshot(session, "compute.session.failed")
                return
        except asyncio.CancelledError:
            raise
        finally:
            self._lease_tasks.pop(session.id, None)

    async def _emit_snapshot(self, session: ComputeSessionSnapshot, event_type: str) -> None:
        if self.state_repository is not None:
            await self.state_repository.save(session)
        await self.events.emit(
            session.id,
            event_type,
            session.model_dump(mode="json", by_alias=True),
        )

    async def _emit_slot(self, session: ComputeSessionSnapshot, slot: ComputeSlot) -> None:
        if self.state_repository is not None:
            await self.state_repository.save(session)
        await self.events.emit(
            session.id,
            "compute.slot.updated",
            slot.model_dump(mode="json", by_alias=True),
        )
