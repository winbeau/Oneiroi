from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from oneiroi_common.compute import ContractModel
from oneiroi_common.studio import GenerationDraft


class CapabilitySupport(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    NOT_PROBED = "not_probed"


class AgentProbeRecord(ContractModel):
    version: Literal[1] = 1
    provider: Literal["openai-responses"] = "openai-responses"
    endpoint_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    tested_model: Annotated[str, Field(min_length=1, max_length=200)]
    image_model: Annotated[str | None, Field(default=None, max_length=200)]
    text: CapabilitySupport = CapabilitySupport.NOT_PROBED
    streaming: CapabilitySupport = CapabilitySupport.NOT_PROBED
    function_tools: CapabilitySupport = CapabilitySupport.NOT_PROBED
    tool_continuation: CapabilitySupport = CapabilitySupport.NOT_PROBED
    image_input: CapabilitySupport = CapabilitySupport.NOT_PROBED
    image_generation: CapabilitySupport = CapabilitySupport.NOT_PROBED
    usage: CapabilitySupport = CapabilitySupport.NOT_PROBED
    error_format: CapabilitySupport = CapabilitySupport.NOT_PROBED
    rate_limit_observed: bool = False
    transport: list[Literal["sse", "websocket"]] = Field(default_factory=list, max_length=2)
    websocket_declared: bool = False
    websocket_verified: bool = False
    probed_at: datetime


class AgentToolRisk(StrEnum):
    READ = "read"
    PROPOSAL = "proposal"
    WRITE = "write"
    COSTLY = "costly"
    DESTRUCTIVE = "destructive"


class AgentToolCapability(ContractModel):
    name: str
    risk: AgentToolRisk
    requires_approval: bool


class AgentCapabilitiesResponse(ContractModel):
    enabled: bool
    configured: bool
    available: bool
    reason_code: str | None = None
    provider: Literal["openai-responses"] | None = None
    model: str | None = None
    text: bool = False
    streaming: bool = False
    function_tools: bool = False
    image_input: bool = False
    image_generation: bool = False
    usage: bool = False
    transports: list[Literal["sse", "websocket"]] = Field(default_factory=list)
    websocket_declared: bool = False
    websocket_verified: bool = False
    tools_enabled: bool = False
    tools: list[AgentToolCapability] = Field(default_factory=list, max_length=32)
    max_turns: int = Field(default=0, ge=0)
    max_tool_calls: int = Field(default=0, ge=0)
    max_approvals: int = Field(default=0, ge=0)


class AgentThreadStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class AgentMessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM_SUMMARY = "system_summary"


class AgentMessageStatus(StrEnum):
    STREAMING = "streaming"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentRunStatus(StrEnum):
    QUEUED = "queued"
    STREAMING = "streaming"
    WAITING_APPROVAL = "waiting_approval"
    EXECUTING_TOOL = "executing_tool"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"
    RECOVERING = "recovering"

    @property
    def is_terminal(self) -> bool:
        return self in {
            AgentRunStatus.CANCELLED,
            AgentRunStatus.COMPLETED,
            AgentRunStatus.FAILED,
            AgentRunStatus.EXPIRED,
        }


class AgentToolCallStatus(StrEnum):
    PROPOSED = "proposed"
    WAITING_APPROVAL = "waiting_approval"
    APPROVED = "approved"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"
    EXPIRED = "expired"


class AgentApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONSUMED = "consumed"
    EXPIRED = "expired"


class DraftProposal(ContractModel):
    prompt: Annotated[str | None, Field(default=None, min_length=1, max_length=4_000)]
    negative_prompt: Annotated[str | None, Field(default=None, max_length=4_000)]
    ratio: Literal["16:9", "9:16", "1:1"] | None = None
    resolution: Literal["720p", "1080p"] | None = None
    duration: Annotated[int | None, Field(default=None, ge=1, le=15)]
    seed: int | None = None
    first_strength: Annotated[float | None, Field(default=None, ge=0, le=1)]
    last_strength: Annotated[float | None, Field(default=None, ge=0, le=1)]
    first_frame_asset_id: Annotated[str | None, Field(default=None, max_length=64)]
    last_frame_asset_id: Annotated[str | None, Field(default=None, max_length=64)]

    @model_validator(mode="after")
    def at_least_one_change(self) -> "DraftProposal":
        if not self.model_dump(exclude_none=True):
            raise ValueError("draft proposal must contain at least one field")
        return self


class AgentMessageContent(ContractModel):
    text: Annotated[str, Field(default="", max_length=20_000)]
    draft_proposal: DraftProposal | None = None
    rationale: list[Annotated[str, Field(max_length=1_000)]] = Field(
        default_factory=list, max_length=12
    )
    warnings: list[Annotated[str, Field(max_length=1_000)]] = Field(
        default_factory=list, max_length=12
    )

    @model_validator(mode="after")
    def visible_content_is_required(self) -> "AgentMessageContent":
        if not self.text.strip() and self.draft_proposal is None:
            raise ValueError("agent message must contain visible text or a draft proposal")
        return self


class AgentRunCreate(ContractModel):
    conversation_id: Annotated[str, Field(min_length=1, max_length=64)]
    message: Annotated[str, Field(min_length=1, max_length=8_000)]
    draft_snapshot: GenerationDraft
    asset_ids: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(
        default_factory=list, max_length=4
    )
    mode: Literal["assist", "image-analysis", "storyboard"] = "assist"


class AgentThreadResponse(ContractModel):
    id: str
    conversation_id: str
    status: AgentThreadStatus
    summary_text: str | None = None
    summary_cursor: int = Field(default=0, ge=0)
    prompt_version: str
    created_at: datetime
    updated_at: datetime


class AgentMessageResponse(ContractModel):
    id: str
    thread_id: str
    run_id: str | None = None
    sequence: int = Field(ge=1)
    role: AgentMessageRole
    content: AgentMessageContent
    status: AgentMessageStatus
    provider_item_id: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class AgentUsage(ContractModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    provider_requests: int = Field(default=0, ge=0)


class AgentRunResponse(ContractModel):
    id: str
    thread_id: str
    conversation_id: str
    status: AgentRunStatus
    model: str
    provider: str
    transport: Literal["sse", "websocket"]
    reasoning_effort: str
    prompt_version: str
    toolset_version: str
    input_snapshot: dict[str, Any]
    usage: AgentUsage = Field(default_factory=AgentUsage)
    provider_response_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    output_message_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AgentEventResponse(ContractModel):
    id: int
    run_id: str
    thread_id: str
    event_type: str
    sequence: int = Field(ge=1)
    payload: dict[str, Any]
    created_at: datetime


class AgentToolCallResponse(ContractModel):
    id: str
    run_id: str
    tool_name: str
    tool_version: str
    risk: AgentToolRisk
    arguments: dict[str, Any]
    arguments_hash: str
    status: AgentToolCallStatus
    result: dict[str, Any] | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AgentApprovalDecision(ContractModel):
    note: Annotated[str | None, Field(default=None, max_length=500)]
    client_version: Annotated[str | None, Field(default=None, max_length=64)]


class AgentApprovalResponse(ContractModel):
    id: str
    run_id: str
    tool_call_id: str
    arguments_hash: str
    status: AgentApprovalStatus
    estimated_cost: str | None = None
    expires_at: datetime
    decided_at: datetime | None = None
    consumed_at: datetime | None = None


class AgentToolDecisionResponse(ContractModel):
    tool_call: AgentToolCallResponse
    approval: AgentApprovalResponse
    run: AgentRunResponse
