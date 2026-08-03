import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from oneiroi_common.agent import AgentToolRisk, DraftProposal
from oneiroi_common.compute import ContractModel
from oneiroi_common.studio import GeneratedImageProvenance, GenerationDraft
from oneiroi_gateway.agent.protocol import (
    AgentProvider,
    AgentProviderError,
    ImageGenerationRequest,
    ProviderTool,
)
from oneiroi_gateway.repositories.agent import AgentExecutionOwned, StoredAgentRun
from oneiroi_gateway.repositories.studio import StudioRepository
from oneiroi_gateway.services.artifact_service import ArtifactService


class SafeAssetMetadata(ContractModel):
    id: str
    type: Literal["image", "video", "template"]
    title: str
    media_type: str
    size_bytes: int
    width: int | None = None
    height: int | None = None
    created_at: str


class SafeJobSnapshot(ContractModel):
    id: str
    conversation_id: str
    stage: str
    progress: int
    attempt: int
    phase: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    output_asset_id: str | None = None
    created_at: str
    updated_at: str


class GetCreationContextArguments(ContractModel):
    conversation_id: Annotated[str, Field(min_length=1, max_length=64)]


class GetCreationContextResult(ContractModel):
    conversation_id: str
    title: str
    draft_snapshot: GenerationDraft
    selected_assets: list[SafeAssetMetadata] = Field(default_factory=list, max_length=4)
    recent_jobs: list[SafeJobSnapshot] = Field(default_factory=list, max_length=3)


class ListAssetsArguments(ContractModel):
    asset_type: Literal["image", "video", "template"] | None = Field(default=None, alias="type")
    query: Annotated[str | None, Field(default=None, max_length=100)]
    limit: int = Field(default=20, ge=1, le=20)


class ListAssetsResult(ContractModel):
    items: list[SafeAssetMetadata] = Field(max_length=20)


class GetAssetMetadataArguments(ContractModel):
    asset_id: Annotated[str, Field(min_length=1, max_length=64)]


class GetAssetMetadataResult(ContractModel):
    asset: SafeAssetMetadata


class GetJobSnapshotArguments(ContractModel):
    job_id: Annotated[str, Field(min_length=1, max_length=64)]


class GetJobSnapshotResult(ContractModel):
    job: SafeJobSnapshot


class ProposeDraftPatchArguments(ContractModel):
    proposal: DraftProposal
    rationale: list[Annotated[str, Field(max_length=1_000)]] = Field(
        default_factory=list, max_length=12
    )
    warnings: list[Annotated[str, Field(max_length=1_000)]] = Field(
        default_factory=list, max_length=12
    )


class ProposeDraftPatchResult(ProposeDraftPatchArguments):
    pass


class GenerateReferenceImageArguments(ContractModel):
    prompt: Annotated[str, Field(min_length=1, max_length=50_000)]
    negative_prompt: Annotated[str | None, Field(default=None, max_length=2_000)]
    purpose: Literal["first-frame", "last-frame", "style-reference"]
    ratio: Literal["21:9", "16:9", "4:3", "1:1", "3:4", "9:16"] = "16:9"
    count: Literal[1, 2] = 1
    reference_asset_ids: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(
        default_factory=list, max_length=4
    )


class GenerateReferenceImageResult(ContractModel):
    assets: list[SafeAssetMetadata] = Field(min_length=1, max_length=2)
    partial: bool = False
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    owner_id: str
    run: StoredAgentRun
    studio: StudioRepository
    tool_call_id: str | None = None
    provider: AgentProvider | None = None
    artifacts: ArtifactService | None = None
    image_model: str | None = None
    max_image_bytes: int = 0
    image_input_available: bool = False
    ensure_execution_owned: Callable[[], Awaitable[None]] | None = None
    consume_provider_events: Callable[[int], Awaitable[None]] | None = None


MAX_TOOL_ARGUMENT_BYTES = 32 * 1024
MAX_TOOL_RESULT_BYTES = 64 * 1024

ToolHandler = Callable[[ToolExecutionContext, BaseModel], Awaitable[BaseModel | dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class RegisteredTool:
    name: str
    version: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    risk: AgentToolRisk
    max_calls_per_run: int
    timeout_seconds: float
    handler: ToolHandler
    estimated_cost: str | None = None
    requires_image_generation: bool = False

    @property
    def requires_approval(self) -> bool:
        return self.risk in {
            AgentToolRisk.WRITE,
            AgentToolRisk.COSTLY,
            AgentToolRisk.DESTRUCTIVE,
        }

    def provider_tool(self) -> ProviderTool:
        return ProviderTool(
            name=self.name,
            description=self.description,
            input_schema=self.input_model.model_json_schema(by_alias=True),
        )


class ToolRegistry:
    def __init__(self, tools: list[RegisteredTool]) -> None:
        self._tools: dict[str, RegisteredTool] = {}
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"duplicate Agent tool: {tool.name}")
            _ = tool.provider_tool()
            self._tools[tool.name] = tool

    def definitions(self, *, image_generation_available: bool = False) -> list[RegisteredTool]:
        return [
            tool
            for tool in self._tools.values()
            if image_generation_available or not tool.requires_image_generation
        ]

    def provider_tools(self, *, image_generation_available: bool = False) -> list[ProviderTool]:
        return [
            tool.provider_tool()
            for tool in self.definitions(image_generation_available=image_generation_available)
        ]

    def require(self, name: str) -> RegisteredTool:
        try:
            return self._tools[name]
        except KeyError:
            raise ValueError("AGENT_TOOL_NOT_ALLOWED") from None

    def validate_arguments(self, name: str, arguments: dict[str, Any]) -> BaseModel:
        return self.require(name).input_model.model_validate(arguments)

    async def execute(
        self,
        name: str,
        context: ToolExecutionContext,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        definition = self.require(name)
        validated = definition.input_model.model_validate(arguments)
        try:
            async with asyncio.timeout(definition.timeout_seconds):
                raw_result = await definition.handler(context, validated)
        except TimeoutError:
            raise RuntimeError("AGENT_TOOL_TIMEOUT") from None
        result = definition.output_model.model_validate(raw_result)
        payload = result.model_dump(mode="json", by_alias=True, exclude_none=True)
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        if len(encoded) > MAX_TOOL_RESULT_BYTES:
            raise RuntimeError("AGENT_TOOL_RESULT_TOO_LARGE")
        return payload


def canonical_arguments(arguments: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
    canonical = json.dumps(
        arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    encoded = canonical.encode()
    if len(encoded) > MAX_TOOL_ARGUMENT_BYTES:
        raise ValueError("AGENT_TOOL_ARGUMENTS_TOO_LARGE")
    return arguments, canonical, hashlib.sha256(encoded).hexdigest()


def builtin_tool_registry(*, image_timeout_seconds: float = 180) -> ToolRegistry:
    return ToolRegistry(
        [
            RegisteredTool(
                name="get_creation_context",
                version="1",
                description=(
                    "Read the current Conversation, submitted draft snapshot, selected safe Asset "
                    "metadata, and up to three recent Job snapshots for this run."
                ),
                input_model=GetCreationContextArguments,
                output_model=GetCreationContextResult,
                risk=AgentToolRisk.READ,
                max_calls_per_run=2,
                timeout_seconds=5,
                handler=_get_creation_context,
            ),
            RegisteredTool(
                name="list_assets",
                version="1",
                description=(
                    "List at most twenty safe metadata records for Assets owned by the "
                    "current user."
                ),
                input_model=ListAssetsArguments,
                output_model=ListAssetsResult,
                risk=AgentToolRisk.READ,
                max_calls_per_run=3,
                timeout_seconds=5,
                handler=_list_assets,
            ),
            RegisteredTool(
                name="get_asset_metadata",
                version="1",
                description="Read safe metadata for one Asset owned by the current user.",
                input_model=GetAssetMetadataArguments,
                output_model=GetAssetMetadataResult,
                risk=AgentToolRisk.READ,
                max_calls_per_run=4,
                timeout_seconds=5,
                handler=_get_asset_metadata,
            ),
            RegisteredTool(
                name="get_job_snapshot",
                version="1",
                description="Read a bounded real Job snapshot owned by the current user.",
                input_model=GetJobSnapshotArguments,
                output_model=GetJobSnapshotResult,
                risk=AgentToolRisk.READ,
                max_calls_per_run=3,
                timeout_seconds=5,
                handler=_get_job_snapshot,
            ),
            RegisteredTool(
                name="propose_draft_patch",
                version="1",
                description=(
                    "Return a validated draft proposal for user review. This never mutates the "
                    "stored draft and never creates a Job."
                ),
                input_model=ProposeDraftPatchArguments,
                output_model=ProposeDraftPatchResult,
                risk=AgentToolRisk.PROPOSAL,
                max_calls_per_run=2,
                timeout_seconds=5,
                handler=_propose_draft_patch,
            ),
            RegisteredTool(
                name="generate_reference_image",
                version="1",
                description=(
                    "Generate one or two owner-bound reference images through the configured "
                    "provider and persist every validated result as a real Asset."
                ),
                input_model=GenerateReferenceImageArguments,
                output_model=GenerateReferenceImageResult,
                risk=AgentToolRisk.COSTLY,
                max_calls_per_run=1,
                timeout_seconds=image_timeout_seconds,
                estimated_cost="external image generation for 1-2 images",
                requires_image_generation=True,
                handler=_generate_reference_image,
            ),
        ]
    )


async def _get_creation_context(
    context: ToolExecutionContext, arguments: BaseModel
) -> GetCreationContextResult:
    parsed = GetCreationContextArguments.model_validate(arguments)
    if parsed.conversation_id != context.run.response.conversation_id:
        raise KeyError(parsed.conversation_id)
    conversation = await context.studio.get_conversation(context.owner_id, parsed.conversation_id)
    assets: list[SafeAssetMetadata] = []
    for asset_id in context.run.response.input_snapshot.get("assetIds", []):
        if not isinstance(asset_id, str):
            continue
        try:
            stored = await context.studio.get_asset(context.owner_id, asset_id)
        except KeyError:
            continue
        assets.append(_safe_asset(stored.response))
    jobs = [
        _safe_job(job)
        for job in await context.studio.list_jobs(context.owner_id)
        if job.conversation_id == parsed.conversation_id
    ][:3]
    return GetCreationContextResult(
        conversationId=conversation.id,
        title=conversation.title[:100],
        draftSnapshot=GenerationDraft.model_validate(
            context.run.response.input_snapshot["draftSnapshot"]
        ),
        selectedAssets=assets,
        recentJobs=jobs,
    )


async def _list_assets(context: ToolExecutionContext, arguments: BaseModel) -> ListAssetsResult:
    parsed = ListAssetsArguments.model_validate(arguments)
    query = parsed.query.casefold() if parsed.query else None
    items = []
    for asset in await context.studio.list_assets(context.owner_id):
        if parsed.asset_type is not None and asset.type != parsed.asset_type:
            continue
        if query is not None and query not in asset.title.casefold():
            continue
        items.append(_safe_asset(asset))
        if len(items) >= parsed.limit:
            break
    return ListAssetsResult(items=items)


async def _get_asset_metadata(
    context: ToolExecutionContext, arguments: BaseModel
) -> GetAssetMetadataResult:
    parsed = GetAssetMetadataArguments.model_validate(arguments)
    stored = await context.studio.get_asset(context.owner_id, parsed.asset_id)
    return GetAssetMetadataResult(asset=_safe_asset(stored.response))


async def _get_job_snapshot(
    context: ToolExecutionContext, arguments: BaseModel
) -> GetJobSnapshotResult:
    parsed = GetJobSnapshotArguments.model_validate(arguments)
    stored = await context.studio.get_job(context.owner_id, parsed.job_id)
    return GetJobSnapshotResult(job=_safe_job(stored.response))


async def _propose_draft_patch(
    context: ToolExecutionContext, arguments: BaseModel
) -> ProposeDraftPatchResult:
    parsed = ProposeDraftPatchArguments.model_validate(arguments)
    for asset_id in (
        parsed.proposal.first_frame_asset_id,
        parsed.proposal.last_frame_asset_id,
    ):
        if asset_id is not None:
            await context.studio.get_asset(context.owner_id, asset_id)
    return ProposeDraftPatchResult(
        proposal=parsed.proposal,
        rationale=parsed.rationale,
        warnings=parsed.warnings,
    )


async def _generate_reference_image(
    context: ToolExecutionContext, arguments: BaseModel
) -> GenerateReferenceImageResult:
    parsed = GenerateReferenceImageArguments.model_validate(arguments)
    if (
        context.provider is None
        or context.artifacts is None
        or context.tool_call_id is None
        or context.image_model is None
        or context.max_image_bytes < 1
    ):
        raise RuntimeError("AGENT_IMAGE_NOT_CONFIGURED")
    if parsed.reference_asset_ids and not context.image_input_available:
        raise RuntimeError("AGENT_IMAGE_NOT_SUPPORTED")
    reference_images = [
        await context.artifacts.provider_image_data_url(
            context.owner_id,
            asset_id,
            max_bytes=context.max_image_bytes,
        )
        for asset_id in parsed.reference_asset_ids
    ]
    prompt_hash = hashlib.sha256(
        json.dumps(
            {"prompt": parsed.prompt, "negativePrompt": parsed.negative_prompt},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    assets: list[SafeAssetMetadata] = []
    partial_error: str | None = None
    for request_index in range(parsed.count):
        if len(assets) >= parsed.count:
            break
        if context.ensure_execution_owned is not None:
            await context.ensure_execution_owned()
        try:
            result = await context.provider.generate_image(
                ImageGenerationRequest(
                    model=context.image_model,
                    prompt=parsed.prompt,
                    negativePrompt=parsed.negative_prompt,
                    request_id=f"{context.tool_call_id}-{request_index}",
                    size={
                        "21:9": "1536x1024",
                        "16:9": "1536x1024",
                        "4:3": "1024x1024",
                        "1:1": "1024x1024",
                        "3:4": "1024x1024",
                        "9:16": "1024x1536",
                    }[parsed.ratio],
                    referenceImages=reference_images,
                )
            )
            if context.consume_provider_events is not None:
                await context.consume_provider_events(result.event_count)
        except AgentProviderError as exc:
            if not assets:
                raise
            partial_error = exc.code.value
            break
        assets_before_response = len(assets)
        for generated in result.images:
            if len(assets) >= parsed.count:
                break
            try:
                if context.ensure_execution_owned is not None:
                    await context.ensure_execution_owned()
                resolved = await context.provider.resolve_generated_image(
                    generated, max_bytes=context.max_image_bytes
                )
                if context.ensure_execution_owned is not None:
                    await context.ensure_execution_owned()
                output_index = len(assets)
                provenance = GeneratedImageProvenance(
                    agentRunId=context.run.response.id,
                    toolCallId=context.tool_call_id,
                    outputIndex=output_index,
                    provider=context.run.response.provider,
                    model=context.image_model,
                    promptSha256=prompt_hash,
                    purpose=parsed.purpose,
                    ratio=parsed.ratio,
                    providerResponseId=result.response_id,
                    createdAt=datetime.now(UTC),
                )
                asset = await context.artifacts.create_generated_image(
                    context.owner_id,
                    resolved.content,
                    {
                        "first-frame": "Agent 首帧参考图",
                        "last-frame": "Agent 尾帧参考图",
                        "style-reference": "Agent 风格参考图",
                    }[parsed.purpose],
                    provenance,
                    max_bytes=context.max_image_bytes,
                    ensure_execution_owned=context.ensure_execution_owned,
                )
                assets.append(_safe_asset(asset))
            except AgentExecutionOwned:
                raise
            except AgentProviderError as exc:
                partial_error = partial_error or exc.code.value
                continue
            except (OSError, RuntimeError, ValueError):
                partial_error = partial_error or "AGENT_IMAGE_INVALID"
                continue
        if len(assets) == assets_before_response:
            break
    if not assets:
        raise RuntimeError(partial_error or "AGENT_IMAGE_REJECTED")
    return GenerateReferenceImageResult(
        assets=assets,
        partial=len(assets) < parsed.count,
        errorCode=partial_error if len(assets) < parsed.count else None,
    )


def _safe_asset(asset: Any) -> SafeAssetMetadata:
    return SafeAssetMetadata(
        id=asset.id,
        type=asset.type,
        title=asset.title[:200],
        mediaType=asset.media_type,
        sizeBytes=asset.size_bytes,
        width=asset.width,
        height=asset.height,
        createdAt=asset.created_at.isoformat(),
    )


def _safe_job(job: Any) -> SafeJobSnapshot:
    return SafeJobSnapshot(
        id=job.id,
        conversationId=job.conversation_id,
        stage=job.stage.value,
        progress=job.progress,
        attempt=job.attempt,
        phase=(job.phase or "")[:100] or None,
        errorCode=job.error.code[:100] if job.error else None,
        errorMessage=job.error.message[:500] if job.error else None,
        outputAssetId=job.output.asset_id if job.output else None,
        createdAt=job.created_at.isoformat(),
        updatedAt=job.updated_at.isoformat(),
    )
