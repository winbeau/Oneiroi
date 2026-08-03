import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx
from redis.asyncio import Redis

from oneiroi_common.compute import GpuInfo, ProfileTier
from oneiroi_common.studio import GenerationDraft
from oneiroi_gateway.redis.leases import Lease
from oneiroi_gateway.services.job_execution import (
    ExecutionEvent,
    JobExecutionContext,
    JobExecutionResult,
)


class GpuServerClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.client = httpx.AsyncClient(
            transport=transport,
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            trust_env=False,
            headers={
                "X-ICTHub-Client": "oneiroi",
                "Authorization": f"Bearer {token}",
            },
        )

    async def request(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
        content: Any = None,
    ) -> httpx.Response:
        response = await self.client.request(
            method,
            path,
            json=json_payload,
            headers=headers,
            content=content,
        )
        if response.status_code >= 400:
            detail = response.text[:500]
            raise RuntimeError(f"GPU_SERVER_HTTP_{response.status_code}: {detail}")
        return response

    async def json(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        response = await self.request(
            method,
            path,
            json_payload=json_payload,
            headers=headers,
        )
        return response.json()

    async def upload(self, path: Path, media_type: str) -> dict[str, Any]:
        async def chunks():
            with path.open("rb") as source:
                while chunk := await asyncio.to_thread(source.read, 1024 * 1024):
                    yield chunk

        response = await self.request(
            "POST",
            "/internal/v1/artifacts",
            headers={
                "Content-Type": media_type,
                "X-Artifact-Filename": path.name,
            },
            content=chunks(),
        )
        return response.json()

    async def download(self, artifact_id: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        async with self.client.stream(
            "GET",
            f"/internal/v1/artifacts/{artifact_id}",
        ) as response:
            if response.status_code >= 400:
                detail = (await response.aread()).decode(errors="replace")[:500]
                raise RuntimeError(f"GPU_SERVER_HTTP_{response.status_code}: {detail}")
            with destination.open("wb") as output:
                async for chunk in response.aiter_bytes():
                    output.write(chunk)

    async def close(self) -> None:
        await self.client.aclose()


class GpuServerInventoryProvider:
    def __init__(self, client: GpuServerClient) -> None:
        self.client = client

    async def list_gpus(self) -> list[GpuInfo]:
        payload = await self.client.json("GET", "/internal/v1/gpus")
        return [GpuInfo.model_validate(item) for item in payload["gpus"]]


class GpuServerLeaseStore:
    prefix = "oneiroi:gpu-server:session:"

    def __init__(
        self,
        client: GpuServerClient,
        redis_url: str,
        *,
        mapping_ttl_seconds: int = 86_400,
    ) -> None:
        self.client = client
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        self.mapping_ttl_seconds = mapping_ttl_seconds

    async def acquire(
        self,
        candidates: list[str],
        requested: int,
        session_id: str,
        *,
        ttl_seconds: float,
        allow_partial: bool,
    ) -> list[Lease]:
        del ttl_seconds
        snapshot = await self.client.json(
            "POST",
            "/internal/v1/leases",
            json_payload={
                "client": "oneiroi",
                "requestedGpuCount": requested,
                "selectionMode": "manual",
                "gpuIds": list(dict.fromkeys(candidates)),
                "profilePolicy": "balanced",
                "allowPartial": allow_partial,
            },
        )
        await self._save(session_id, snapshot)
        return _leases(session_id, snapshot)

    async def renew_session(self, session_id: str, *, ttl_seconds: float) -> list[str]:
        del ttl_seconds
        mapping = await self._mapping(session_id)
        if mapping is None:
            return []
        snapshot = await self.client.json(
            "POST",
            f"/internal/v1/leases/{mapping['leaseId']}/renew",
        )
        await self._save(session_id, snapshot)
        return list(snapshot["gpuIds"])

    async def release_gpu(self, gpu_id: str, session_id: str) -> bool:
        mapping = await self._mapping(session_id)
        if mapping is None or gpu_id not in mapping["gpuIds"]:
            return False
        return bool(await self.release_session(session_id))

    async def release_session(self, session_id: str) -> list[str]:
        mapping = await self._mapping(session_id)
        if mapping is None:
            return []
        snapshot = await self.client.json(
            "POST",
            f"/internal/v1/leases/{mapping['leaseId']}/release",
            json_payload={"policy": "when_idle"},
        )
        if snapshot["state"] == "released":
            await self.redis.delete(self._key(session_id))
            return list(mapping["gpuIds"])
        return []

    async def active(self) -> dict[str, Lease]:
        result: dict[str, Lease] = {}
        keys = [key async for key in self.redis.scan_iter(f"{self.prefix}*")]
        for key in keys:
            value = await self.redis.get(key)
            if not value:
                continue
            session_id = key.removeprefix(self.prefix)
            mapping = json.loads(value)
            try:
                snapshot = await self.client.json(
                    "GET",
                    f"/internal/v1/leases/{mapping['leaseId']}",
                )
            except RuntimeError as exc:
                if "GPU_SERVER_HTTP_404" in str(exc):
                    await self.redis.delete(key)
                    continue
                raise
            if snapshot["state"] not in {"active", "releasing"}:
                continue
            result.update({lease.gpu_id: lease for lease in _leases(session_id, snapshot)})
        return result

    async def remote_lease_id(self, session_id: str) -> str:
        mapping = await self._mapping(session_id)
        if mapping is None:
            raise RuntimeError("GPU_SERVER_LEASE_NOT_FOUND")
        return str(mapping["leaseId"])

    async def close(self) -> None:
        await self.redis.aclose()
        await self.client.close()

    async def _save(self, session_id: str, snapshot: dict[str, Any]) -> None:
        await self.redis.set(
            self._key(session_id),
            json.dumps(
                {
                    "leaseId": snapshot["id"],
                    "gpuIds": snapshot["gpuIds"],
                    "gpuFencingTokens": snapshot["gpuFencingTokens"],
                },
                separators=(",", ":"),
            ),
            ex=self.mapping_ttl_seconds,
        )

    async def _mapping(self, session_id: str) -> dict[str, Any] | None:
        value = await self.redis.get(self._key(session_id))
        return json.loads(value) if value else None

    def _key(self, session_id: str) -> str:
        return f"{self.prefix}{session_id}"


class GpuServerComputeBackend:
    async def load_slot(
        self,
        session_id: str,
        slot_id: str,
        gpu: GpuInfo,
        profile: ProfileTier,
        fencing_token: str,
    ) -> dict[str, object]:
        del session_id, slot_id, gpu, profile, fencing_token
        return {"pipelineSpecHash": "gpu-server-on-demand"}

    async def release_slot(
        self,
        session_id: str,
        slot,
        fencing_token: str,
    ) -> bool:
        del session_id, slot, fencing_token
        return True


class GpuServerJobExecutor:
    def __init__(
        self,
        client: GpuServerClient,
        leases: GpuServerLeaseStore,
        *,
        poll_seconds: float = 0.5,
    ) -> None:
        self.client = client
        self.leases = leases
        self.poll_seconds = poll_seconds

    async def execute(
        self,
        job_id: str,
        draft: GenerationDraft,
        job_directory: Path,
        input_paths: tuple[Path | None, Path | None],
        on_event: ExecutionEvent,
        is_cancelled,
        context: JobExecutionContext,
    ) -> JobExecutionResult:
        artifact_ids: list[str | None] = []
        for path in input_paths:
            if path is None:
                artifact_ids.append(None)
                continue
            media_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
            artifact = await self.client.upload(path, media_type)
            artifact_ids.append(str(artifact["id"]))
        width, height = _dimensions(draft.resolution, draft.ratio)
        frames = round((int(draft.duration) * 24 - 1) / 8) * 8 + 1
        inputs: dict[str, object] = {
            "prompt": draft.prompt,
            "negativePrompt": draft.negative_prompt,
            "width": width,
            "height": height,
            "numFrames": frames,
            "fps": 24,
            "seed": draft.seed,
            "quality": draft.profile.value,
            "duration": int(draft.duration),
            "enhancePrompt": draft.enhance_prompt,
            "firstFrameStrength": draft.first_strength,
            "lastFrameStrength": draft.last_strength,
        }
        if artifact_ids[0]:
            inputs["firstFrameArtifactId"] = artifact_ids[0]
        if artifact_ids[1]:
            inputs["lastFrameArtifactId"] = artifact_ids[1]
        lease_id = await self.leases.remote_lease_id(context.session_id)
        snapshot = await self.client.json(
            "POST",
            "/internal/v1/jobs",
            json_payload={
                "externalJobId": job_id,
                "client": "oneiroi",
                "leaseId": lease_id,
                "workloadType": "oneiroi.ltx2.i2v",
                "profileId": "ltx23-distilled-fast-v1",
                "inputs": inputs,
            },
            headers={"Idempotency-Key": f"oneiroi-{job_id}-{context.attempt}"},
        )
        remote_job_id = str(snapshot["id"])
        cancelled_sent = False
        last_event: tuple[object, ...] | None = None
        while snapshot["status"] not in {
            "succeeded",
            "failed",
            "cancelled",
            "timed_out",
            "lost",
        }:
            if is_cancelled() and not cancelled_sent:
                await self.client.json(
                    "POST",
                    f"/internal/v1/jobs/{remote_job_id}/cancel",
                )
                cancelled_sent = True
            phase = str(snapshot.get("phase") or snapshot["status"])
            progress = snapshot.get("progress")
            signature = (snapshot["status"], phase, progress)
            if signature != last_event:
                await on_event(phase, int(progress or 0), {})
                last_event = signature
            await asyncio.sleep(self.poll_seconds)
            snapshot = await self.client.json(
                "GET",
                f"/internal/v1/jobs/{remote_job_id}",
            )
        if snapshot["status"] == "cancelled":
            raise asyncio.CancelledError
        if snapshot["status"] != "succeeded":
            error = snapshot.get("error") or {}
            code = error.get("code") or snapshot["status"].upper()
            message = error.get("message") or code
            raise RuntimeError(f"{code}: {message}")
        artifact = snapshot["result"][0]
        output = job_directory / "output" / "result.mp4"
        await self.client.download(str(artifact["id"]), output)
        manifest = job_directory / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "jobId": job_id,
                    "attempt": context.attempt,
                    "profileId": snapshot["profileId"],
                    "request": inputs,
                    "gpuServerJobId": remote_job_id,
                    "artifact": artifact,
                    "effectiveParameters": {
                        "width": width,
                        "height": height,
                        "numFrames": frames,
                        "fps": 24,
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return JobExecutionResult(
            output_path=output,
            manifest_path=manifest,
            warm_start=False,
            metrics={"gpuServerJobId": remote_job_id},
        )


def _leases(session_id: str, snapshot: dict[str, Any]) -> list[Lease]:
    expires = time.monotonic() + 300
    return [
        Lease(
            gpu_id=gpu_id,
            session_id=session_id,
            fencing_token=snapshot["gpuFencingTokens"][gpu_id],
            expires_at_monotonic=expires,
        )
        for gpu_id in snapshot["gpuIds"]
    ]


def _dimensions(resolution: str, ratio: str) -> tuple[int, int]:
    if resolution == "1080p":
        landscape = {"21:9": 2544, "16:9": 1920, "4:3": 1456, "1:1": 1088}
        height = 1088
    else:
        landscape = {"21:9": 1648, "16:9": 1280, "4:3": 944, "1:1": 704}
        height = 704
    if ratio in landscape:
        return landscape[ratio], height
    portrait = {"3:4": "4:3", "9:16": "16:9"}[ratio]
    return height, landscape[portrait]
