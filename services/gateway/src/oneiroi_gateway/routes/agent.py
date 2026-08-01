from fastapi import APIRouter

from oneiroi_common.agent import AgentCapabilitiesResponse
from oneiroi_gateway.services.agent_capabilities import AgentCapabilityService


def create_agent_router(capabilities: AgentCapabilityService) -> APIRouter:
    router = APIRouter(prefix="/v1/agent", tags=["agent"])

    @router.get(
        "/capabilities",
        response_model=AgentCapabilitiesResponse,
        response_model_by_alias=True,
    )
    async def get_capabilities() -> AgentCapabilitiesResponse:
        return capabilities.get()

    return router
