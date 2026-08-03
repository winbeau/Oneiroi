from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from oneiroi_common.agent import AgentProbeRecord


class ProviderErrorCode(StrEnum):
    NOT_CONFIGURED = "AGENT_NOT_CONFIGURED"
    PROVIDER_UNAVAILABLE = "AGENT_PROVIDER_UNAVAILABLE"
    AUTH_FAILED = "AGENT_AUTH_FAILED"
    RATE_LIMITED = "AGENT_RATE_LIMITED"
    CONTEXT_TOO_LARGE = "AGENT_CONTEXT_TOO_LARGE"
    OUTPUT_INVALID = "AGENT_OUTPUT_INVALID"
    STREAM_INTERRUPTED = "AGENT_STREAM_INTERRUPTED"
    TOOL_ARGUMENTS_INVALID = "AGENT_TOOL_ARGUMENTS_INVALID"
    IMAGE_NOT_SUPPORTED = "AGENT_IMAGE_NOT_SUPPORTED"
    IMAGE_REJECTED = "AGENT_IMAGE_REJECTED"
    CANCELLED = "AGENT_CANCELLED"


class AgentProviderError(RuntimeError):
    def __init__(
        self,
        code: ProviderErrorCode,
        *,
        status_code: int | None = None,
        request_id: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        self.code = code
        self.status_code = status_code
        self.request_id = request_id
        self.retry_after_seconds = retry_after_seconds
        detail = code.value
        if status_code is not None:
            detail += f" status={status_code}"
        if request_id:
            detail += f" request_id={request_id[:128]}"
        super().__init__(detail)


class ProviderTool(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")]
    description: Annotated[str, Field(min_length=1, max_length=1_000)]
    input_schema: dict[str, Any]

    @field_validator("input_schema")
    @classmethod
    def strict_object_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        if value.get("type") != "object":
            raise ValueError("tool input schema must be an object schema")
        _require_strict_objects(value)
        return value


class ProviderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: Annotated[str, Field(min_length=1, max_length=200)]
    instructions: Annotated[str, Field(min_length=1, max_length=20_000)]
    input_items: list[dict[str, Any]] = Field(default_factory=list, max_length=64)
    tools: list[ProviderTool] = Field(default_factory=list, max_length=32)
    builtin_tools: list[Literal["image_generation"]] = Field(default_factory=list, max_length=1)
    image_size: Annotated[str | None, Field(default=None, max_length=40)] = None
    image_quality: Annotated[str | None, Field(default=None, max_length=40)] = None
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh"] = "high"
    max_output_tokens: Annotated[int, Field(ge=1, le=100_000)] = 4_000
    store: Literal[False] = False
    request_id: Annotated[str, Field(min_length=1, max_length=128)]
    tool_choice: str | dict[str, Any] | None = None


class ProviderEventType(StrEnum):
    RESPONSE_STARTED = "response.started"
    TEXT_DELTA = "text.delta"
    TEXT_COMPLETED = "text.completed"
    REASONING_DELTA = "reasoning.delta"
    REASONING_COMPLETED = "reasoning.completed"
    TOOL_ARGUMENTS_DELTA = "tool.arguments.delta"
    TOOL_PROPOSED = "tool.proposed"
    IMAGE_STARTED = "image.started"
    IMAGE_COMPLETED = "image.completed"
    USAGE_COMPLETED = "usage.completed"
    RESPONSE_COMPLETED = "response.completed"
    RESPONSE_FAILED = "response.failed"


class ProviderEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_type: ProviderEventType
    provider_event_id: str | None = None
    response_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class ImageGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: Annotated[str, Field(min_length=1, max_length=200)]
    prompt: Annotated[str, Field(min_length=1, max_length=50_000)]
    request_id: Annotated[str, Field(min_length=1, max_length=128)]
    size: Annotated[str | None, Field(default=None, max_length=40)]
    quality: Annotated[str | None, Field(default=None, max_length=40)]
    negative_prompt: Annotated[str | None, Field(default=None, max_length=2_000)] = Field(
        default=None, alias="negativePrompt"
    )
    reference_images: list[Annotated[str, Field(max_length=140_000_000)]] = Field(
        default_factory=list, alias="referenceImages", max_length=4
    )


class GeneratedImage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    base64_data: str | None = Field(default=None, alias="base64Data")
    file_id: str | None = Field(default=None, alias="fileId")
    url: str | None = None
    media_type: str | None = Field(default=None, alias="mediaType")


class ImageGenerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    images: list[GeneratedImage] = Field(min_length=1, max_length=2)
    response_id: str | None = None
    event_count: int = Field(default=0, ge=0, le=10_000)


class ResolvedGeneratedImage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content: bytes
    media_type: str | None = None


def _require_strict_objects(schema: Any) -> None:
    if isinstance(schema, dict):
        if schema.get("type") == "object" and schema.get("additionalProperties") is not False:
            raise ValueError("every object in a tool schema must forbid additional properties")
        for value in schema.values():
            _require_strict_objects(value)
    elif isinstance(schema, list):
        for value in schema:
            _require_strict_objects(value)


class AgentProvider(Protocol):
    async def stream_response(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]: ...

    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResult: ...

    async def resolve_generated_image(
        self, image: GeneratedImage, *, max_bytes: int
    ) -> ResolvedGeneratedImage: ...

    async def probe(
        self,
        *,
        include_image_generation: bool = False,
        probe_error_format: bool = False,
    ) -> AgentProbeRecord: ...

    async def close(self) -> None: ...
