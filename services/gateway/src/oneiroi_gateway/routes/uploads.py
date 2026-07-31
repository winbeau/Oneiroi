from typing import Annotated

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile, status

from oneiroi_common.studio import AssetResponse
from oneiroi_gateway.services.artifact_service import ArtifactService


def create_upload_router(artifacts: ArtifactService) -> APIRouter:
    router = APIRouter(prefix="/v1/uploads", tags=["uploads"])

    @router.post(
        "/images",
        response_model=AssetResponse,
        response_model_by_alias=True,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_image(
        file: Annotated[UploadFile, File()],
        title: Annotated[str | None, Form()] = None,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> AssetResponse:
        try:
            return await artifacts.upload_image(user, file, title)
        except ValueError as exc:
            detail = str(exc)
            status_code = (
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
                if detail == "UPLOAD_TOO_LARGE"
                else status.HTTP_422_UNPROCESSABLE_ENTITY
            )
            raise HTTPException(status_code=status_code, detail=detail) from exc

    return router
