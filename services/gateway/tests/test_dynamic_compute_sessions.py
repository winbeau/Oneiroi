import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from oneiroi_common.compute import (
    ComputeSessionCreate,
    ComputeSessionRelease,
    GpuInfo,
    GpuState,
    ProfileTier,
)
from oneiroi_gateway.main import create_app
from oneiroi_gateway.redis.leases import InMemoryLeaseStore
from oneiroi_gateway.services.compute_sessions import (
    ComputeSessionService,
    RecordingComputeBackend,
)
from oneiroi_gateway.services.gpu_inventory import GpuInventoryService, InMemoryInventoryProvider
from oneiroi_gateway.settings import GatewaySettings


def gpu(index: int, *, eligible: bool = True) -> GpuInfo:
    return GpuInfo(
        id=f"GPU-{index:04d}",
        physicalIndex=index,
        name="NVIDIA H100 80GB HBM3",
        vramTotalMiB=81_559,
        vramUsedMiB=0 if eligible else 40_000,
        state=GpuState.EMPTY if eligible else GpuState.FOREIGN_BUSY,
        eligible=eligible,
        unavailableReason=None if eligible else "EXTERNAL_COMPUTE_PROCESS",
    )


def dynamic_service():
    inventory = GpuInventoryService(
        InMemoryInventoryProvider([gpu(7), gpu(2), gpu(3, eligible=False), gpu(0)])
    )
    backend = RecordingComputeBackend()
    leases = InMemoryLeaseStore()
    service = ComputeSessionService(inventory, backend, leases=leases)
    return inventory, backend, leases, service


@pytest.mark.asyncio
async def test_request_four_with_three_idle_allocates_two_fast_one_hq() -> None:
    _, backend, leases, service = dynamic_service()

    session = await service.create(
        "user-a",
        ComputeSessionCreate(requestedGpuCount=4),
    )

    assert session.allocated_gpu_count == 3
    assert session.profile_plan.fast == 2
    assert session.profile_plan.hq == 1
    assert session.state.value == "degraded"
    assert [slot.physical_index for slot in session.slots] == [0, 2, 7]
    assert [item[3] for item in backend.loaded] == [
        ProfileTier.FAST,
        ProfileTier.FAST,
        ProfileTier.HQ,
    ]
    assert set(await leases.active()) == {"GPU-0000", "GPU-0002", "GPU-0007"}
    assert "GPU-0003" not in await leases.active()


@pytest.mark.asyncio
async def test_manual_selection_rejects_foreign_busy_gpu() -> None:
    _, _, _, service = dynamic_service()
    with pytest.raises(ValueError, match="GPU_NOT_ELIGIBLE"):
        await service.create(
            "user-a",
            ComputeSessionCreate(
                requestedGpuCount=1,
                selectionMode="manual",
                gpuIds=["GPU-0003"],
            ),
        )


@pytest.mark.asyncio
async def test_competing_sessions_do_not_share_gpu() -> None:
    inventory = GpuInventoryService(InMemoryInventoryProvider([gpu(7)]))
    leases = InMemoryLeaseStore()
    service = ComputeSessionService(
        inventory,
        RecordingComputeBackend(),
        leases=leases,
    )
    results = await asyncio.gather(
        service.create("user-a", ComputeSessionCreate(requestedGpuCount=1)),
        service.create("user-b", ComputeSessionCreate(requestedGpuCount=1)),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, BaseException) for result in results) == 1
    assert len(await leases.active()) == 1


@pytest.mark.asyncio
async def test_heartbeat_loss_marks_slot_and_clears_only_stale_lease() -> None:
    _, _, leases, service = dynamic_service()
    session = await service.create("user-a", ComputeSessionCreate(requestedGpuCount=3))
    stale_gpu = session.slots[0].gpu_id

    affected = await service.reconcile_stale_gpus({stale_gpu})

    assert affected == [session.id]
    assert session.state.value == "degraded"
    assert session.slots[0].last_error == "RUNNER_HEARTBEAT_LOST"
    assert stale_gpu not in await leases.active()
    assert len(await leases.active()) == 2


@pytest.mark.asyncio
async def test_session_renews_lease_during_slow_model_load() -> None:
    class SlowBackend(RecordingComputeBackend):
        async def load_slot(
            self,
            session_id,
            slot_id,
            selected_gpu,
            profile,
            fencing_token,
        ):
            await asyncio.sleep(0.08)
            return await super().load_slot(
                session_id,
                slot_id,
                selected_gpu,
                profile,
                fencing_token,
            )

    inventory = GpuInventoryService(InMemoryInventoryProvider([gpu(7)]))
    leases = InMemoryLeaseStore()
    service = ComputeSessionService(
        inventory,
        SlowBackend(),
        leases=leases,
        lease_ttl_seconds=0.03,
    )

    session = await service.create("user-a", ComputeSessionCreate(requestedGpuCount=1))

    assert (await leases.active())["GPU-0007"].session_id == session.id
    await service.release("user-a", session.id, ComputeSessionRelease())
    await service.close()


@pytest.mark.asyncio
async def test_redis_renewal_failure_marks_session_failed() -> None:
    class FailingRenewalStore(InMemoryLeaseStore):
        async def renew_session(self, session_id: str, *, ttl_seconds: float):
            del session_id, ttl_seconds
            raise ConnectionError("redis unavailable")

    inventory = GpuInventoryService(InMemoryInventoryProvider([gpu(7)]))
    service = ComputeSessionService(
        inventory,
        RecordingComputeBackend(),
        leases=FailingRenewalStore(),
        lease_ttl_seconds=0.03,
    )
    session = await service.create("user-a", ComputeSessionCreate(requestedGpuCount=1))

    for _ in range(20):
        if session.state.value == "failed":
            break
        await asyncio.sleep(0.01)

    assert session.error_code == "REDIS_LEASE_RENEWAL_FAILED"
    await service.close()


@pytest.mark.asyncio
async def test_failed_memory_release_keeps_lease_renewed() -> None:
    class FailedReleaseBackend(RecordingComputeBackend):
        async def release_slot(self, session_id, slot, fencing_token):
            del session_id, slot, fencing_token
            return False

    inventory = GpuInventoryService(InMemoryInventoryProvider([gpu(7)]))
    leases = InMemoryLeaseStore()
    service = ComputeSessionService(
        inventory,
        FailedReleaseBackend(),
        leases=leases,
        lease_ttl_seconds=0.03,
    )
    session = await service.create("user-a", ComputeSessionCreate(requestedGpuCount=1))
    released = await service.release("user-a", session.id, ComputeSessionRelease())
    await asyncio.sleep(0.05)

    assert released.state.value == "failed"
    assert (await leases.active())["GPU-0007"].session_id == session.id
    await service.close()


@pytest.mark.asyncio
async def test_idle_ttl_releases_worker_and_gpu_lease() -> None:
    inventory = GpuInventoryService(InMemoryInventoryProvider([gpu(7)]))
    leases = InMemoryLeaseStore()
    backend = RecordingComputeBackend()
    service = ComputeSessionService(
        inventory,
        backend,
        leases=leases,
        lease_ttl_seconds=0.03,
        idle_ttl_seconds=0.05,
    )
    session = await service.create("user-a", ComputeSessionCreate(requestedGpuCount=1))

    for _ in range(50):
        if session.state.value == "released":
            break
        await asyncio.sleep(0.01)

    assert session.state.value == "released"
    assert backend.released == [(session.id, session.slots[0].id)]
    assert await leases.active() == {}
    await service.close()


@pytest.mark.asyncio
async def test_session_sse_replays_events_and_release_terminal_event() -> None:
    inventory, _, _, service = dynamic_service()
    app = create_app(
        GatewaySettings(),
        inventory_service=inventory,
        compute_session_service=service,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/v1/compute/sessions", json={"requestedGpuCount": 1})
        session_id = created.json()["id"]
        await client.post(
            f"/v1/compute/sessions/{session_id}/release",
            json={"policy": "when_idle"},
        )
        response = await client.get(f"/v1/compute/sessions/{session_id}/events")

    assert response.status_code == 200
    assert "event: compute.slot.updated" in response.text
    assert "event: compute.session.ready" in response.text
    assert "event: compute.session.released" in response.text
    ids = [
        int(line.removeprefix("id: "))
        for line in response.text.splitlines()
        if line.startswith("id: ")
    ]
    assert ids == sorted(ids)
