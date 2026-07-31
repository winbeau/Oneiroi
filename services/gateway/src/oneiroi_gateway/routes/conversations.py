from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status

from oneiroi_common.studio import ConversationCreate, ConversationPut, ConversationResponse
from oneiroi_gateway.repositories.studio import StudioRepository


def create_conversation_router(repository: StudioRepository) -> APIRouter:
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

    return router
