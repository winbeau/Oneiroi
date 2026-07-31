from fastapi import APIRouter

from oneiroi_common.compute import GpuInventoryResponse
from oneiroi_gateway.services.gpu_inventory import GpuInventoryService


def create_compute_router(inventory: GpuInventoryService) -> APIRouter:
    router = APIRouter(prefix="/v1/compute", tags=["compute"])

    @router.get("/gpus", response_model=GpuInventoryResponse, response_model_by_alias=True)
    async def get_gpus() -> GpuInventoryResponse:
        return await inventory.snapshot()

    return router
