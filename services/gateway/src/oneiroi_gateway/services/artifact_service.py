import asyncio
import base64
import fcntl
import hashlib
import io
import os
import warnings
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from oneiroi_common.studio import AssetResponse, GeneratedImageProvenance
from oneiroi_gateway.repositories.studio import StoredAsset, StudioRepository

ALLOWED_IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


class ArtifactService:
    def __init__(
        self,
        repository: StudioRepository,
        storage_root: Path,
        *,
        max_upload_bytes: int,
        max_image_pixels: int = 33_554_432,
        max_image_edge: int = 8_192,
    ) -> None:
        self.repository = repository
        self.storage_root = storage_root.resolve()
        self.max_upload_bytes = max_upload_bytes
        self.max_image_pixels = max_image_pixels
        self.max_image_edge = max_image_edge

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

    async def provider_image_data_url(
        self,
        owner_id: str,
        asset_id: str,
        *,
        max_bytes: int,
    ) -> str:
        stored = await self.repository.get_asset(owner_id, asset_id)
        if stored.response.type != "image":
            raise ValueError("INVALID_IMAGE_ASSET")
        path = stored.storage_path.resolve()
        if (
            not path.is_relative_to(self.storage_root)
            or not path.is_file()
            or path.stat().st_size > max_bytes
        ):
            raise ValueError("INVALID_IMAGE_ASSET")
        content = path.read_bytes()
        normalized, _, _, _ = self._normalize_image(
            content,
            max_bytes=max_bytes,
            resize=True,
        )
        encoded = base64.b64encode(normalized).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    async def create_generated_image(
        self,
        owner_id: str,
        image_bytes: bytes,
        title: str,
        provenance: GeneratedImageProvenance,
        *,
        max_bytes: int,
        ensure_execution_owned: Callable[[], Awaitable[None]] | None = None,
    ) -> AssetResponse:
        asset_id = self._generated_asset_id(
            owner_id, provenance.tool_call_id, provenance.output_index
        )
        async with self._generated_asset_lock(asset_id):
            return await self._create_generated_image_locked(
                owner_id,
                image_bytes,
                title,
                provenance,
                max_bytes=max_bytes,
                ensure_execution_owned=ensure_execution_owned,
            )

    async def _create_generated_image_locked(
        self,
        owner_id: str,
        image_bytes: bytes,
        title: str,
        provenance: GeneratedImageProvenance,
        *,
        max_bytes: int,
        ensure_execution_owned: Callable[[], Awaitable[None]] | None,
    ) -> AssetResponse:
        asset_id = self._generated_asset_id(
            owner_id, provenance.tool_call_id, provenance.output_index
        )
        try:
            existing = await self.repository.get_asset(owner_id, asset_id)
        except KeyError:
            existing = None
        if existing is not None:
            self._validate_committed_generated_asset(existing, provenance)
            return existing.response.model_copy(deep=True)

        content, width, height, sha256 = self._normalize_image(
            image_bytes,
            max_bytes=max_bytes,
            resize=False,
        )
        if ensure_execution_owned is not None:
            await ensure_execution_owned()
        path = self._asset_path(asset_id, "generated.png")
        partial = path.with_name(f"{path.name}.partial")
        path.parent.mkdir(parents=True, exist_ok=True)
        partial.unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        try:
            with partial.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(partial, path)
        except Exception:
            partial.unlink(missing_ok=True)
            path.unlink(missing_ok=True)
            with suppress(OSError):
                path.parent.rmdir()
            raise
        if ensure_execution_owned is not None:
            await ensure_execution_owned()
        response = AssetResponse(
            id=asset_id,
            type="image",
            title=title[:200],
            createdAt=provenance.created_at,
            mediaType="image/png",
            sizeBytes=len(content),
            width=width,
            height=height,
            previewUrl=f"/v1/assets/{asset_id}/file",
            provenance=provenance,
        )
        stored = StoredAsset(
            owner_id=owner_id,
            response=response,
            storage_path=path,
            sha256=sha256,
        )
        try:
            created = await self.repository.create_asset(stored)
        except Exception as create_error:
            try:
                committed = await self.repository.get_asset(owner_id, asset_id)
            except KeyError:
                path.unlink(missing_ok=True)
                with suppress(OSError):
                    path.parent.rmdir()
                raise create_error from None
            self._validate_committed_generated_asset(committed, provenance)
            created = committed.response.model_copy(deep=True)
        if ensure_execution_owned is not None:
            await ensure_execution_owned()
        return created

    async def cleanup_unregistered_generated_images(self, owner_id: str, tool_call_id: str) -> None:
        for output_index in range(2):
            asset_id = self._generated_asset_id(owner_id, tool_call_id, output_index)
            async with self._generated_asset_lock(asset_id):
                try:
                    await self.repository.get_asset(owner_id, asset_id)
                except KeyError:
                    path = self._asset_path(asset_id, "generated.png")
                    path.with_name(f"{path.name}.partial").unlink(missing_ok=True)
                    path.unlink(missing_ok=True)
                    with suppress(OSError):
                        path.parent.rmdir()

    async def list_generated_images(self, owner_id: str, tool_call_id: str) -> list[AssetResponse]:
        return sorted(
            [
                asset
                for asset in await self.repository.list_assets(owner_id)
                if asset.provenance is not None
                and asset.provenance.source_type == "agent-image"
                and asset.provenance.tool_call_id == tool_call_id
            ],
            key=lambda asset: asset.provenance.output_index if asset.provenance else 0,
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

    def _normalize_image(
        self,
        content: bytes,
        *,
        max_bytes: int,
        resize: bool,
    ) -> tuple[bytes, int, int, str]:
        if not content or len(content) > max_bytes:
            raise ValueError("IMAGE_TOO_LARGE")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(content)) as image:
                    if getattr(image, "is_animated", False):
                        raise ValueError("ANIMATED_IMAGE_NOT_SUPPORTED")
                    image.verify()
                with Image.open(io.BytesIO(content)) as image:
                    width, height = image.size
                    if width < 1 or height < 1:
                        raise ValueError("INVALID_IMAGE")
                    if width * height > self.max_image_pixels:
                        raise ValueError("IMAGE_DIMENSIONS_EXCEEDED")
                    if max(width, height) > self.max_image_edge:
                        if not resize:
                            raise ValueError("IMAGE_DIMENSIONS_EXCEEDED")
                        scale = self.max_image_edge / max(width, height)
                        target = (max(1, int(width * scale)), max(1, int(height * scale)))
                        image.thumbnail(target, Image.Resampling.LANCZOS)
                    image = ImageOps.exif_transpose(image)
                    normalized = image.convert("RGBA" if image.mode in {"RGBA", "LA"} else "RGB")
                    width, height = normalized.size
                    output = io.BytesIO()
                    normalized.save(output, format="PNG", optimize=True)
        except ValueError:
            raise
        except (
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
            UnidentifiedImageError,
            OSError,
            SyntaxError,
        ) as exc:
            raise ValueError("INVALID_IMAGE") from exc
        encoded = output.getvalue()
        if not encoded or len(encoded) > max_bytes:
            raise ValueError("IMAGE_TOO_LARGE")
        return encoded, width, height, hashlib.sha256(encoded).hexdigest()

    @asynccontextmanager
    async def _generated_asset_lock(self, asset_id: str):
        lock_directory = (self.storage_root / ".agent-image-locks").resolve()
        if not lock_directory.is_relative_to(self.storage_root):
            raise ValueError("invalid asset lock path")
        lock_directory.mkdir(parents=True, exist_ok=True)
        handle = (lock_directory / f"{asset_id}.lock").open("a+b")
        lock_task = asyncio.create_task(
            asyncio.to_thread(fcntl.flock, handle.fileno(), fcntl.LOCK_EX)
        )
        try:
            await asyncio.shield(lock_task)
        except asyncio.CancelledError:
            await lock_task
            await asyncio.to_thread(fcntl.flock, handle.fileno(), fcntl.LOCK_UN)
            handle.close()
            raise
        try:
            yield
        finally:
            await asyncio.to_thread(fcntl.flock, handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def _validate_committed_generated_asset(
        self,
        stored: StoredAsset,
        expected: GeneratedImageProvenance,
    ) -> None:
        actual = stored.response.provenance
        path = stored.storage_path.resolve()
        expected_path = self._asset_path(stored.response.id, "generated.png")
        if (
            actual is None
            or actual.source_type != "agent-image"
            or actual.tool_call_id != expected.tool_call_id
            or actual.output_index != expected.output_index
            or actual.prompt_sha256 != expected.prompt_sha256
            or actual.provider != expected.provider
            or actual.model != expected.model
            or actual.purpose != expected.purpose
            or actual.ratio != expected.ratio
            or path != expected_path
            or not path.is_file()
            or path.stat().st_size != stored.response.size_bytes
        ):
            raise ValueError("GENERATED_ASSET_CONFLICT")
        with path.open("rb") as handle:
            sha256 = hashlib.file_digest(handle, "sha256").hexdigest()
        if sha256 != stored.sha256:
            raise ValueError("GENERATED_ASSET_CONFLICT")

    @staticmethod
    def _generated_asset_id(owner_id: str, tool_call_id: str, output_index: int) -> str:
        asset_seed = f"{owner_id}:{tool_call_id}:{output_index}"
        return f"asset-{hashlib.sha256(asset_seed.encode()).hexdigest()[:20]}"

    def _asset_path(self, asset_id: str, filename: str) -> Path:
        path = (self.storage_root / "assets" / asset_id / filename).resolve()
        if not path.is_relative_to(self.storage_root):
            raise ValueError("invalid asset id")
        return path
