import pytest
from httpx import ASGITransport, AsyncClient

from oneiroi_common.compute import GpuInfo, GpuState
from oneiroi_common.errors import ErrorCode
from oneiroi_gateway.main import create_app
from oneiroi_gateway.services.capabilities import CapabilityService
from oneiroi_gateway.services.compute_sessions import (
    ComputeSessionService,
    RecordingComputeBackend,
)
from oneiroi_gateway.services.gpu_inventory import GpuInventoryService, InMemoryInventoryProvider
from oneiroi_gateway.settings import GatewaySettings


def make_inventory(count: int) -> GpuInventoryService:
    return GpuInventoryService(
        InMemoryInventoryProvider(
            [
                GpuInfo(
                    id=f"GPU-{index:04d}",
                    physicalIndex=index,
                    name="NVIDIA H100 80GB HBM3",
                    vramTotalMiB=81_559,
                    state=GpuState.EMPTY,
                    eligible=True,
                )
                for index in range(count)
            ]
        )
    )


@pytest.mark.asyncio
async def test_one_gpu_session_hard_disables_hq() -> None:
    inventory = make_inventory(1)
    sessions = ComputeSessionService(inventory, RecordingComputeBackend())
    app = create_app(
        GatewaySettings(),
        inventory_service=inventory,
        compute_session_service=sessions,
        capability_service=CapabilityService(),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/v1/compute/sessions", json={"requestedGpuCount": 1})
        response = await client.get(
            "/v1/compute/capabilities",
            params={"sessionId": created.json()["id"]},
        )

    assert response.status_code == 200
    profiles = {profile["tier"]: profile for profile in response.json()["profiles"]}
    assert profiles["fast"]["available"] is True
    assert profiles["hq"]["available"] is False
    assert (
        profiles["hq"]["unavailableReason"]
        == ErrorCode.HQ_REQUIRES_AT_LEAST_2_GPUS.value
    )


@pytest.mark.asyncio
async def test_two_gpu_session_exposes_ready_hq() -> None:
    inventory = make_inventory(2)
    sessions = ComputeSessionService(inventory, RecordingComputeBackend())
    app = create_app(
        GatewaySettings(),
        inventory_service=inventory,
        compute_session_service=sessions,
        capability_service=CapabilityService(),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/v1/compute/sessions", json={"requestedGpuCount": 2})
        response = await client.get(
            "/v1/compute/capabilities",
            params={"sessionId": created.json()["id"]},
        )

    profiles = {profile["tier"]: profile for profile in response.json()["profiles"]}
    assert profiles["fast"]["available"] is True
    assert profiles["hq"]["available"] is True
