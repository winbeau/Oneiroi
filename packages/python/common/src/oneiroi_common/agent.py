from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from oneiroi_common.compute import ContractModel


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
