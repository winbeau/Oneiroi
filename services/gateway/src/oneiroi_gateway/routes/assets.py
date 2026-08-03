from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Response, status
from fastapi.responses import FileResponse

from oneiroi_common.studio import AssetResponse
from oneiroi_gateway.repositories.studio import StudioRepository
from oneiroi_gateway.services.artifact_service import ArtifactService

# Asset ids are immutable content addresses: once created, the bytes never change,
# so browsers may cache the file forever and only refresh the list incrementally.
IMMUTABLE_CACHE_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}


def create_asset_router(
    repository: StudioRepository,
    artifacts: ArtifactService,
) -> APIRouter:
    router = APIRouter(prefix="/v1/assets", tags=["assets"])

    @router.get("", response_model=list[AssetResponse], response_model_by_alias=True)
    async def list_assets(
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> list[AssetResponse]:
        return await repository.list_assets(user)

    @router.get("/{asset_id}/file")
    async def get_asset_file(
        asset_id: str,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> FileResponse:
        try:
            asset = await artifacts.get_asset(user, asset_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        return FileResponse(
            asset.storage_path,
            media_type=asset.response.media_type,
            headers=IMMUTABLE_CACHE_HEADERS,
        )

    @router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_asset(
        asset_id: str,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> Response:
        try:
            await artifacts.delete_asset(user, asset_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
