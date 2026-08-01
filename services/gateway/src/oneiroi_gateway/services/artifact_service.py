import hashlib
import io
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

from oneiroi_common.studio import AssetResponse
from oneiroi_gateway.repositories.studio import StoredAsset, StudioRepository

ALLOWED_IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


class ArtifactService:
    def __init__(
        self,
        repository: StudioRepository,
        storage_root: Path,
        *,
        max_upload_bytes: int,
    ) -> None:
        self.repository = repository
        self.storage_root = storage_root.resolve()
        self.max_upload_bytes = max_upload_bytes

    async def upload_image(
        self,
        owner_id: str,
        upload: UploadFile,
        title: str | None = None,
    ) -> AssetResponse:
        media_type = upload.content_type or ""
        suffix = ALLOWED_IMAGE_TYPES.get(media_type)
        if suffix is None:
            raise ValueError("INVALID_MIME_TYPE")
        content = await upload.read(self.max_upload_bytes + 1)
        if not content or len(content) > self.max_upload_bytes:
            raise ValueError("UPLOAD_TOO_LARGE")
        try:
            with Image.open(io.BytesIO(content)) as image:
                image.verify()
            with Image.open(io.BytesIO(content)) as image:
                width, height = image.size
        except (UnidentifiedImageError, OSError, SyntaxError) as exc:
            raise ValueError("INVALID_IMAGE") from exc

        asset_id = f"asset-{uuid4().hex[:20]}"
        path = self._asset_path(asset_id, f"input{suffix}")
        path.parent.mkdir(parents=True, exist_ok=False)
        path.write_bytes(content)
        response = AssetResponse(
            id=asset_id,
            type="image",
            title=(title or upload.filename or "参考图")[:200],
            createdAt=datetime.now(UTC),
            mediaType=media_type,
            sizeBytes=len(content),
            width=width,
            height=height,
            previewUrl=f"/v1/assets/{asset_id}/file",
        )
        return await self.repository.create_asset(
            StoredAsset(
                owner_id=owner_id,
                response=response,
                storage_path=path,
                sha256=hashlib.sha256(content).hexdigest(),
            )
        )

    async def register_video(
        self,
        owner_id: str,
        job_id: str,
        source_path: Path,
    ) -> AssetResponse:
        resolved = source_path.resolve()
        if not resolved.is_relative_to(self.storage_root):
            raise ValueError("ARTIFACT_PATH_OUTSIDE_STORAGE")
        if not resolved.is_file() or resolved.suffix.lower() != ".mp4":
            raise ValueError("INVALID_VIDEO_ARTIFACT")
        content_hash = hashlib.sha256(resolved.read_bytes()).hexdigest()
        asset_id = f"asset-{uuid4().hex[:20]}"
        response = AssetResponse(
            id=asset_id,
            type="video",
            title="生成视频",
            createdAt=datetime.now(UTC),
            mediaType="video/mp4",
            sizeBytes=resolved.stat().st_size,
            sourceJobId=job_id,
            previewUrl=f"/v1/jobs/{job_id}/file",
        )
        return await self.repository.create_asset(
            StoredAsset(
                owner_id=owner_id,
                response=response,
                storage_path=resolved,
                sha256=content_hash,
            )
        )

    async def get_asset(self, owner_id: str, asset_id: str) -> StoredAsset:
        return await self.repository.get_asset(owner_id, asset_id)

    async def delete_asset(self, owner_id: str, asset_id: str) -> None:
        asset = await self.repository.get_asset(owner_id, asset_id)
        await self.repository.delete_asset(owner_id, asset_id)
        if asset.response.source_job_id is None:
            asset.storage_path.unlink(missing_ok=True)

    def job_directory(self, job_id: str) -> Path:
        path = (self.storage_root / "jobs" / job_id).resolve()
        if not path.is_relative_to(self.storage_root):
            raise ValueError("invalid job id")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _asset_path(self, asset_id: str, filename: str) -> Path:
        path = (self.storage_root / "assets" / asset_id / filename).resolve()
        if not path.is_relative_to(self.storage_root):
            raise ValueError("invalid asset id")
        return path
