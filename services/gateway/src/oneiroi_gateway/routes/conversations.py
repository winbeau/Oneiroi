from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Response, status

from oneiroi_common.studio import ConversationCreate, ConversationPut, ConversationResponse
from oneiroi_gateway.repositories.studio import StudioRepository
from oneiroi_gateway.services.artifact_service import ArtifactService


def create_conversation_router(
    repository: StudioRepository,
    artifacts: ArtifactService | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/v1/conversations", tags=["conversations"])

    @router.get("", response_model=list[ConversationResponse], response_model_by_alias=True)
    async def list_conversations(
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> list[ConversationResponse]:
        return await repository.list_conversations(user)

    @router.post(
        "",
        response_model=ConversationResponse,
        response_model_by_alias=True,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_conversation(
        payload: ConversationCreate,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> ConversationResponse:
        return await repository.create_conversation(user, payload.title)

    @router.get(
        "/{conversation_id}",
        response_model=ConversationResponse,
        response_model_by_alias=True,
    )
    async def get_conversation(
        conversation_id: str,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> ConversationResponse:
        try:
            return await repository.get_conversation(user, conversation_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc

    @router.put(
        "/{conversation_id}",
        response_model=ConversationResponse,
        response_model_by_alias=True,
    )
    async def put_conversation(
        conversation_id: str,
        payload: ConversationPut,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> ConversationResponse:
        try:
            return await repository.put_conversation(user, conversation_id, payload.title)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc

    @router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_conversation(
        conversation_id: str,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> Response:
        if artifacts is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "ARTIFACTS_UNAVAILABLE",
                    "message": "Artifact service is not configured.",
                },
            )
        try:
            await artifacts.delete_conversation(user, conversation_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
