import pytest
from httpx import ASGITransport, AsyncClient

from oneiroi_common.compute import GpuInfo, GpuState
from oneiroi_gateway.main import create_app
from oneiroi_gateway.services.gpu_inventory import GpuInventoryService, InMemoryInventoryProvider
from oneiroi_gateway.settings import GatewaySettings


@pytest.mark.asyncio
async def test_inventory_uses_uuid_and_preserves_non_contiguous_indexes() -> None:
    provider = InMemoryInventoryProvider(
        [
            GpuInfo(
                id=f"GPU-{index:04d}",
                physicalIndex=index,
                name="NVIDIA H100 80GB HBM3",
                vramTotalMiB=81_559,
                state=GpuState.EMPTY,
                eligible=True,
            )
            for index in (7, 0, 2, 1)
        ]
    )
    app = create_app(GatewaySettings(), inventory_service=GpuInventoryService(provider))
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/compute/gpus")

    assert response.status_code == 200
    body = response.json()
    assert body["requestedDefault"] == 4
    assert body["maximumSelectable"] == 4
    assert [gpu["physicalIndex"] for gpu in body["gpus"]] == [0, 1, 2, 7]
    assert all(gpu["id"].startswith("GPU-") for gpu in body["gpus"])
