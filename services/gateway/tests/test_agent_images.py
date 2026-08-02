import asyncio
import base64
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image, PngImagePlugin

from oneiroi_common.agent import AgentRunStatus
from oneiroi_common.studio import AssetResponse, GeneratedImageProvenance
from oneiroi_gateway.agent.fake import FakeAgentProvider
from oneiroi_gateway.agent.protocol import (
    AgentProviderError,
    GeneratedImage,
    ImageGenerationRequest,
    ImageGenerationResult,
    ProviderErrorCode,
    ProviderEvent,
    ProviderEventType,
)
from oneiroi_gateway.main import create_app as create_gateway_app
from oneiroi_gateway.repositories.agent import InMemoryAgentRepository
from oneiroi_gateway.repositories.studio import InMemoryStudioRepository, StoredAsset
from oneiroi_gateway.services.artifact_service import ArtifactService
from oneiroi_gateway.settings import GatewaySettings


def create_app(settings: GatewaySettings, **kwargs: Any):
    return create_gateway_app(settings, allow_unprobed_agent_provider_for_tests=True, **kwargs)


def image_settings(tmp_path: Path, **overrides: Any) -> GatewaySettings:
    values: dict[str, Any] = {
        "_env_file": None,
        "storage_root": tmp_path,
        "agent_enabled": True,
        "agent_api_key": "test-key",
        "agent_base_url": "https://provider.invalid/v1",
        "agent_tools_enabled": True,
        "agent_image_enabled": True,
        "agent_image_model": "fake-image-model",
    }
    values.update(overrides)
    return GatewaySettings(**values)


def png_bytes(
    size: tuple[int, int] = (2, 2),
    *,
    color: tuple[int, int, int] = (20, 80, 160),
    metadata: bool = False,
) -> bytes:
    output = io.BytesIO()
    png_info = PngImagePlugin.PngInfo()
    if metadata:
        png_info.add_text("secret-note", "must be stripped")
    Image.new("RGB", size, color).save(output, format="PNG", pnginfo=png_info)
    return output.getvalue()


def image_tool_turn(call_id: str, arguments: dict[str, object]) -> list[ProviderEvent]:
    return [
        ProviderEvent(event_type=ProviderEventType.RESPONSE_STARTED),
        ProviderEvent(
            event_type=ProviderEventType.TOOL_PROPOSED,
            data={
                "callId": call_id,
                "name": "generate_reference_image",
                "arguments": arguments,
                "argumentsJson": json.dumps(
                    arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ),
            },
        ),
        ProviderEvent(event_type=ProviderEventType.RESPONSE_COMPLETED),
    ]


def final_turn(text: str = "Image saved for review.") -> list[ProviderEvent]:
    payload = json.dumps({"text": text}, ensure_ascii=False, separators=(",", ":"))
    return [
        ProviderEvent(event_type=ProviderEventType.RESPONSE_STARTED),
        ProviderEvent(event_type=ProviderEventType.TEXT_DELTA, data={"delta": payload}),
        ProviderEvent(event_type=ProviderEventType.RESPONSE_COMPLETED),
    ]


class CommitThenRaiseRepository(InMemoryStudioRepository):
    async def create_asset(self, asset: StoredAsset) -> AssetResponse:
        await super().create_asset(asset)
        raise RuntimeError("commit result was lost")


class FailingAssetRepository(InMemoryStudioRepository):
    async def create_asset(self, asset: StoredAsset) -> AssetResponse:
        del asset
        raise RuntimeError("repository write failed")


async def wait_for_status(client: AsyncClient, run_id: str, expected: set[str]) -> dict[str, Any]:
    for _ in range(200):
        response = await client.get(
            f"/v1/agent/runs/{run_id}", headers={"X-Oneiroi-User": "owner-a"}
        )
        snapshot = response.json()
        if snapshot["status"] in expected:
            return snapshot
        await asyncio.sleep(0.01)
    raise AssertionError(f"run did not reach {expected}")


@pytest.mark.asyncio
async def test_generated_artifact_is_normalized_atomic_and_idempotent(tmp_path: Path) -> None:
    repository = InMemoryStudioRepository()
    service = ArtifactService(
        repository,
        tmp_path,
        max_upload_bytes=1024 * 1024,
        max_image_pixels=100,
        max_image_edge=10,
    )
    provenance = GeneratedImageProvenance(
        agentRunId="agent-run-1",
        toolCallId="agent-tool-1",
        outputIndex=0,
        provider="fake",
        model="fake-image-model",
        promptSha256="a" * 64,
        purpose="first-frame",
        ratio="16:9",
        providerResponseId="response-image-1",
        createdAt=datetime.now(UTC),
    )
    created = await service.create_generated_image(
        "owner-a",
        png_bytes(metadata=True),
        "Generated frame",
        provenance,
        max_bytes=1024 * 1024,
    )
    stored = await repository.get_asset("owner-a", created.id)
    assert created.media_type == "image/png"
    assert created.provenance == provenance
    assert stored.storage_path.name == "generated.png"
    assert stored.storage_path.read_bytes().startswith(b"\x89PNG")
    with Image.open(stored.storage_path) as image:
        assert "secret-note" not in image.info
    assert not list(tmp_path.rglob("*.partial"))

    replay = await service.create_generated_image(
        "owner-a",
        png_bytes(color=(255, 0, 0)),
        "Replacement must not overwrite",
        provenance.model_copy(update={"created_at": datetime.now(UTC)}),
        max_bytes=1024 * 1024,
    )
    assert replay.id == created.id
    assert (await repository.list_assets("owner-a")) == [created]
    with pytest.raises(KeyError):
        await repository.get_asset("owner-b", created.id)
    with pytest.raises(ValueError, match="IMAGE_DIMENSIONS_EXCEEDED"):
        await service.create_generated_image(
            "owner-a",
            png_bytes((20, 20)),
            "Too large",
            provenance.model_copy(update={"output_index": 1}),
            max_bytes=1024 * 1024,
        )

    failing_root = tmp_path / "failing"
    failing_service = ArtifactService(
        FailingAssetRepository(), failing_root, max_upload_bytes=1024 * 1024
    )
    with pytest.raises(RuntimeError, match="repository write failed"):
        await failing_service.create_generated_image(
            "owner-a",
            png_bytes(),
            "Must roll back",
            provenance,
            max_bytes=1024 * 1024,
        )
    assert not list(failing_root.rglob("generated.png"))
    assert not list(failing_root.rglob("*.partial"))

    unknown_root = tmp_path / "unknown-commit"
    unknown_repository = CommitThenRaiseRepository()
    unknown_service = ArtifactService(
        unknown_repository, unknown_root, max_upload_bytes=1024 * 1024
    )
    recovered = await unknown_service.create_generated_image(
        "owner-a",
        png_bytes(),
        "Committed before response loss",
        provenance,
        max_bytes=1024 * 1024,
    )
    recovered_stored = await unknown_repository.get_asset("owner-a", recovered.id)
    assert recovered_stored.storage_path.is_file()
    assert not list(unknown_root.rglob("*.partial"))

    fenced_root = tmp_path / "post-commit-fence"
    fenced_repository = InMemoryStudioRepository()
    fenced_service = ArtifactService(fenced_repository, fenced_root, max_upload_bytes=1024 * 1024)
    checks = 0

    async def lose_lease_after_commit() -> None:
        nonlocal checks
        checks += 1
        if checks == 3:
            raise RuntimeError("execution lease lost after commit")

    with pytest.raises(RuntimeError, match="execution lease lost after commit"):
        await fenced_service.create_generated_image(
            "owner-a",
            png_bytes(),
            "Preserve committed asset",
            provenance,
            max_bytes=1024 * 1024,
            ensure_execution_owned=lose_lease_after_commit,
        )
    fenced_assets = await fenced_repository.list_assets("owner-a")
    assert len(fenced_assets) == 1
    assert (
        await fenced_repository.get_asset("owner-a", fenced_assets[0].id)
    ).storage_path.is_file()

    concurrent_root = tmp_path / "concurrent"
    concurrent_repository = InMemoryStudioRepository()
    concurrent_service = ArtifactService(
        concurrent_repository, concurrent_root, max_upload_bytes=1024 * 1024
    )
    first, second = await asyncio.gather(
        concurrent_service.create_generated_image(
            "owner-a",
            png_bytes(color=(255, 0, 0)),
            "Concurrent red",
            provenance,
            max_bytes=1024 * 1024,
        ),
        concurrent_service.create_generated_image(
            "owner-a",
            png_bytes(color=(0, 0, 255)),
            "Concurrent blue",
            provenance,
            max_bytes=1024 * 1024,
        ),
    )
    assert first.id == second.id
    concurrent_assets = await concurrent_repository.list_assets("owner-a")
    assert len(concurrent_assets) == 1
    concurrent_stored = await concurrent_repository.get_asset("owner-a", concurrent_assets[0].id)
    assert concurrent_stored.storage_path.is_file()
    assert not list(concurrent_root.rglob("*.partial"))


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["base64", "file", "url"])
async def test_approved_image_tool_assetizes_all_provider_return_modes(
    tmp_path: Path, mode: str
) -> None:
    content = png_bytes()
    payloads: dict[str, bytes] = {}
    if mode == "base64":
        generated = GeneratedImage(
            base64Data=base64.b64encode(content).decode("ascii"), mediaType="image/png"
        )
    elif mode == "file":
        generated = GeneratedImage(fileId="file-generated-1", mediaType="image/png")
        payloads["file-generated-1"] = content
    else:
        generated = GeneratedImage(
            url="https://provider.invalid/v1/generated/1", mediaType="image/png"
        )
        payloads[generated.url or ""] = content
    provider = FakeAgentProvider(
        event_batches=[
            image_tool_turn(
                "call-image",
                {
                    "prompt": "A calm dawn lake",
                    "purpose": "first-frame",
                    "ratio": "16:9",
                    "count": 1,
                    "referenceAssetIds": [],
                },
            ),
            final_turn(),
        ],
        image_generation=True,
        generated_images=[generated],
        image_payloads=payloads,
    )
    repository = InMemoryStudioRepository()
    agent_repository = InMemoryAgentRepository()
    conversation = await repository.create_conversation("owner-a", "Generated image")
    app = create_app(
        image_settings(tmp_path),
        agent_provider=provider,
        agent_repository=agent_repository,
        repository=repository,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/v1/agent/runs",
            headers={"X-Oneiroi-User": "owner-a", "Idempotency-Key": f"image-{mode}"},
            json={
                "conversationId": conversation.id,
                "message": "Generate a reference frame",
                "draftSnapshot": {"prompt": "lake"},
            },
        )
        waiting = await wait_for_status(client, created.json()["id"], {"waiting_approval"})
        assert provider.image_requests == []
        assert await repository.list_assets("owner-a") == []
        tool_call = (await agent_repository.list_tool_calls("owner-a", waiting["id"]))[0]
        approved = await client.post(
            f"/v1/agent/tool-calls/{tool_call.response.id}/approve",
            headers={"X-Oneiroi-User": "owner-a"},
            json={"note": "one image"},
        )
        assert approved.status_code == 202
        terminal = await wait_for_status(client, waiting["id"], {"completed"})
        assets = await repository.list_assets("owner-a")
        download = await client.get(
            f"/v1/assets/{assets[0].id}/file",
            headers={"X-Oneiroi-User": "owner-a"},
        )
    assert terminal["status"] == AgentRunStatus.COMPLETED.value
    assert len(provider.image_requests) == 1
    assert provider.image_requests[0].model == "fake-image-model"
    assert len(assets) == 1
    assert assets[0].provenance is not None
    assert assets[0].provenance.tool_call_id == tool_call.response.id
    assert assets[0].provenance.prompt_sha256 != "A calm dawn lake"
    assert download.status_code == 200
    assert download.content.startswith(b"\x89PNG")
    continuation = next(
        item
        for item in provider.requests[1].input_items
        if item.get("type") == "function_call_output"
    )
    assert assets[0].id in str(continuation["output"])
    assert str(tmp_path) not in str(continuation)
    await app.state.agent_runtime.close()


@pytest.mark.asyncio
async def test_invalid_first_provider_image_does_not_discard_later_valid_image(
    tmp_path: Path,
) -> None:
    content = png_bytes()
    provider = FakeAgentProvider(
        event_batches=[
            image_tool_turn(
                "call-mixed-images",
                {
                    "prompt": "Choose the valid output",
                    "purpose": "style-reference",
                    "ratio": "1:1",
                    "count": 1,
                    "referenceAssetIds": [],
                },
            ),
            final_turn(),
        ],
        image_generation=True,
        generated_images=[
            GeneratedImage(base64Data="not-valid-base64", mediaType="image/png"),
            GeneratedImage(
                base64Data=base64.b64encode(content).decode("ascii"),
                mediaType="image/png",
            ),
        ],
    )
    repository = InMemoryStudioRepository()
    agent_repository = InMemoryAgentRepository()
    conversation = await repository.create_conversation("owner-a", "Mixed image output")
    app = create_app(
        image_settings(tmp_path),
        agent_provider=provider,
        agent_repository=agent_repository,
        repository=repository,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/v1/agent/runs",
            headers={"X-Oneiroi-User": "owner-a", "Idempotency-Key": "mixed-images"},
            json={
                "conversationId": conversation.id,
                "message": "Generate a valid image",
                "draftSnapshot": {"prompt": "lake"},
            },
        )
        waiting = await wait_for_status(client, created.json()["id"], {"waiting_approval"})
        tool_call = (await agent_repository.list_tool_calls("owner-a", waiting["id"]))[0]
        await client.post(
            f"/v1/agent/tool-calls/{tool_call.response.id}/approve",
            headers={"X-Oneiroi-User": "owner-a"},
            json={},
        )
        await wait_for_status(client, waiting["id"], {"completed"})
    stored_call = await agent_repository.get_tool_call("owner-a", tool_call.response.id)
    assert stored_call.response.status.value == "succeeded"
    assert stored_call.response.result is not None
    assert stored_call.response.result["partial"] is False
    assert len(await repository.list_assets("owner-a")) == 1
    await app.state.agent_runtime.close()


@pytest.mark.asyncio
async def test_cross_owner_reference_image_never_reaches_provider(tmp_path: Path) -> None:
    repository = InMemoryStudioRepository()
    other_asset_id = "asset-owner-b-reference"
    other_path = tmp_path / "assets" / other_asset_id / "input.png"
    other_path.parent.mkdir(parents=True)
    other_path.write_bytes(png_bytes())
    await repository.create_asset(
        StoredAsset(
            "owner-b",
            AssetResponse(
                id=other_asset_id,
                type="image",
                title="Private owner B frame",
                createdAt=datetime.now(UTC),
                mediaType="image/png",
                sizeBytes=other_path.stat().st_size,
                width=2,
                height=2,
            ),
            other_path,
            "c" * 64,
        )
    )
    conversation = await repository.create_conversation("owner-a", "Owner isolation")
    provider = FakeAgentProvider(
        event_batches=[
            image_tool_turn(
                "call-cross-owner-image",
                {
                    "prompt": "Use the private reference",
                    "purpose": "style-reference",
                    "ratio": "1:1",
                    "count": 1,
                    "referenceAssetIds": [other_asset_id],
                },
            ),
            final_turn("Reference was unavailable."),
        ],
        image_generation=True,
        image_input=True,
    )
    agent_repository = InMemoryAgentRepository()
    app = create_app(
        image_settings(tmp_path, agent_image_input_enabled=True),
        agent_provider=provider,
        agent_repository=agent_repository,
        repository=repository,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/v1/agent/runs",
            headers={"X-Oneiroi-User": "owner-a", "Idempotency-Key": "cross-owner-image"},
            json={
                "conversationId": conversation.id,
                "message": "Use another owner's image",
                "draftSnapshot": {"prompt": "lake"},
            },
        )
        waiting = await wait_for_status(client, created.json()["id"], {"waiting_approval"})
        tool_call = (await agent_repository.list_tool_calls("owner-a", waiting["id"]))[0]
        await client.post(
            f"/v1/agent/tool-calls/{tool_call.response.id}/approve",
            headers={"X-Oneiroi-User": "owner-a"},
            json={},
        )
        await wait_for_status(client, waiting["id"], {"completed"})
    stored_call = await agent_repository.get_tool_call("owner-a", tool_call.response.id)
    assert stored_call.response.error_code == "AGENT_RESOURCE_NOT_FOUND"
    assert provider.image_requests == []
    assert await repository.list_assets("owner-a") == []
    await app.state.agent_runtime.close()


@pytest.mark.asyncio
async def test_selected_image_is_sanitized_before_provider_input(tmp_path: Path) -> None:
    repository = InMemoryStudioRepository()
    asset_id = "asset-input-image"
    path = tmp_path / "assets" / asset_id / "input.png"
    path.parent.mkdir(parents=True)
    path.write_bytes(png_bytes(metadata=True))
    asset = AssetResponse(
        id=asset_id,
        type="image",
        title="Reference",
        createdAt=datetime.now(UTC),
        mediaType="image/png",
        sizeBytes=path.stat().st_size,
        width=2,
        height=2,
        previewUrl=f"/v1/assets/{asset_id}/file",
    )
    await repository.create_asset(StoredAsset("owner-a", asset, path, "b" * 64))
    conversation = await repository.create_conversation("owner-a", "Image input")
    provider = FakeAgentProvider(events=final_turn("Image inspected."), image_input=True)
    app = create_app(
        image_settings(
            tmp_path,
            agent_tools_enabled=False,
            agent_image_enabled=False,
            agent_image_input_enabled=True,
        ),
        agent_provider=provider,
        repository=repository,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/v1/agent/runs",
            headers={"X-Oneiroi-User": "owner-a", "Idempotency-Key": "image-input-1"},
            json={
                "conversationId": conversation.id,
                "message": "Inspect this image",
                "draftSnapshot": {"prompt": "lake"},
                "assetIds": [asset_id],
            },
        )
        terminal = await wait_for_status(client, created.json()["id"], {"completed"})
    assert terminal["status"] == "completed"
    user_item = next(
        item for item in provider.requests[0].input_items if item.get("role") == "user"
    )
    image_item = next(item for item in user_item["content"] if item.get("type") == "input_image")
    assert str(image_item["image_url"]).startswith("data:image/png;base64,")
    assert str(path) not in str(provider.requests[0].input_items)
    decoded = base64.b64decode(str(image_item["image_url"]).split(",", 1)[1])
    with Image.open(io.BytesIO(decoded)) as image:
        assert "secret-note" not in image.info
    await app.state.agent_runtime.close()


@pytest.mark.asyncio
async def test_invalid_selected_image_fails_before_provider_call(tmp_path: Path) -> None:
    repository = InMemoryStudioRepository()
    asset_id = "asset-invalid-image"
    path = tmp_path / "assets" / asset_id / "input.png"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not-an-image")
    await repository.create_asset(
        StoredAsset(
            "owner-a",
            AssetResponse(
                id=asset_id,
                type="image",
                title="Broken image",
                createdAt=datetime.now(UTC),
                mediaType="image/png",
                sizeBytes=path.stat().st_size,
                width=1,
                height=1,
            ),
            path,
            "d" * 64,
        )
    )
    conversation = await repository.create_conversation("owner-a", "Invalid input")
    provider = FakeAgentProvider(events=final_turn(), image_input=True)
    app = create_app(
        image_settings(
            tmp_path,
            agent_tools_enabled=False,
            agent_image_enabled=False,
            agent_image_input_enabled=True,
        ),
        agent_provider=provider,
        repository=repository,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/v1/agent/runs",
            headers={"X-Oneiroi-User": "owner-a", "Idempotency-Key": "invalid-image"},
            json={
                "conversationId": conversation.id,
                "message": "Inspect broken image",
                "draftSnapshot": {"prompt": "lake"},
                "assetIds": [asset_id],
            },
        )
        failed = await wait_for_status(client, created.json()["id"], {"failed"})
    assert failed["errorCode"] == "AGENT_IMAGE_INVALID"
    assert provider.requests == []
    await app.state.agent_runtime.close()


class PartialImageProvider(FakeAgentProvider):
    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        if self.image_requests:
            self.image_requests.append(request)
            raise AgentProviderError(ProviderErrorCode.IMAGE_REJECTED)
        return await super().generate_image(request)


@pytest.mark.asyncio
async def test_partial_image_success_keeps_validated_asset(tmp_path: Path) -> None:
    content = png_bytes()
    provider = PartialImageProvider(
        event_batches=[
            image_tool_turn(
                "call-partial-image",
                {
                    "prompt": "Create two options",
                    "purpose": "last-frame",
                    "ratio": "9:16",
                    "count": 2,
                    "referenceAssetIds": [],
                },
            ),
            final_turn("One option was saved."),
        ],
        image_generation=True,
        generated_images=[
            GeneratedImage(
                base64Data=base64.b64encode(content).decode("ascii"),
                mediaType="image/png",
            )
        ],
    )
    repository = InMemoryStudioRepository()
    agent_repository = InMemoryAgentRepository()
    conversation = await repository.create_conversation("owner-a", "Partial image")
    app = create_app(
        image_settings(tmp_path),
        agent_provider=provider,
        agent_repository=agent_repository,
        repository=repository,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/v1/agent/runs",
            headers={"X-Oneiroi-User": "owner-a", "Idempotency-Key": "partial-image"},
            json={
                "conversationId": conversation.id,
                "message": "Generate two images",
                "draftSnapshot": {"prompt": "lake"},
            },
        )
        waiting = await wait_for_status(client, created.json()["id"], {"waiting_approval"})
        tool_call = (await agent_repository.list_tool_calls("owner-a", waiting["id"]))[0]
        await client.post(
            f"/v1/agent/tool-calls/{tool_call.response.id}/approve",
            headers={"X-Oneiroi-User": "owner-a"},
            json={},
        )
        await wait_for_status(client, waiting["id"], {"completed"})
    stored_call = await agent_repository.get_tool_call("owner-a", tool_call.response.id)
    assert stored_call.response.status.value == "succeeded"
    assert stored_call.response.result is not None
    assert stored_call.response.result["partial"] is True
    assert stored_call.response.result["errorCode"] == "AGENT_IMAGE_REJECTED"
    assert len(await repository.list_assets("owner-a")) == 1
    assert len(provider.image_requests) == 2
    await app.state.agent_runtime.close()


class BlockingGeneratedArtifactService(ArtifactService):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.created = asyncio.Event()
        self.release = asyncio.Event()

    async def create_generated_image(self, *args: Any, **kwargs: Any) -> AssetResponse:
        asset = await super().create_generated_image(*args, **kwargs)
        self.created.set()
        await self.release.wait()
        return asset


@pytest.mark.asyncio
async def test_interrupted_image_tool_preserves_known_asset_without_replay(tmp_path: Path) -> None:
    content = png_bytes()
    provider = FakeAgentProvider(
        event_batches=[
            image_tool_turn(
                "call-interrupted-image",
                {
                    "prompt": "A safe reference",
                    "purpose": "style-reference",
                    "ratio": "1:1",
                    "count": 1,
                    "referenceAssetIds": [],
                },
            )
        ],
        image_generation=True,
        generated_images=[
            GeneratedImage(
                base64Data=base64.b64encode(content).decode("ascii"),
                mediaType="image/png",
            )
        ],
    )
    repository = InMemoryStudioRepository()
    agent_repository = InMemoryAgentRepository()
    artifacts = BlockingGeneratedArtifactService(
        repository,
        tmp_path,
        max_upload_bytes=1024 * 1024,
    )
    conversation = await repository.create_conversation("owner-a", "Interrupted image")
    app = create_app(
        image_settings(tmp_path),
        agent_provider=provider,
        agent_repository=agent_repository,
        artifact_service=artifacts,
        repository=repository,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/v1/agent/runs",
            headers={"X-Oneiroi-User": "owner-a", "Idempotency-Key": "image-interrupt-1"},
            json={
                "conversationId": conversation.id,
                "message": "Generate then interrupt",
                "draftSnapshot": {"prompt": "lake"},
            },
        )
        waiting = await wait_for_status(client, created.json()["id"], {"waiting_approval"})
        tool_call = (await agent_repository.list_tool_calls("owner-a", waiting["id"]))[0]
        await client.post(
            f"/v1/agent/tool-calls/{tool_call.response.id}/approve",
            headers={"X-Oneiroi-User": "owner-a"},
            json={},
        )
        await asyncio.wait_for(artifacts.created.wait(), timeout=3)
    await app.state.agent_runtime.close()
    stored_call = await agent_repository.get_tool_call("owner-a", tool_call.response.id)
    assets = await repository.list_assets("owner-a")
    snapshot = await agent_repository.get_run("owner-a", waiting["id"])
    assert snapshot.response.status is AgentRunStatus.FAILED
    assert stored_call.response.error_code == "AGENT_TOOL_RECOVERY_REQUIRED"
    assert stored_call.response.result is not None
    assert assets[0].id in str(stored_call.response.result)
    assert len(provider.image_requests) == 1
    assert not list(tmp_path.rglob("*.partial"))
