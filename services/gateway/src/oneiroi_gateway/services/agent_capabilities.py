import os
import stat
from pathlib import Path

from pydantic import ValidationError

from oneiroi_common.agent import (
    AgentCapabilitiesResponse,
    AgentProbeRecord,
    AgentToolCapability,
    CapabilitySupport,
)
from oneiroi_gateway.agent.endpoint import provider_endpoint_hash
from oneiroi_gateway.agent.registry import ToolRegistry, builtin_tool_registry
from oneiroi_gateway.settings import GatewaySettings


class AgentCapabilityService:
    def __init__(
        self, settings: GatewaySettings, tool_registry: ToolRegistry | None = None
    ) -> None:
        self.settings = settings
        self.tool_registry = tool_registry or builtin_tool_registry()

    def get(self) -> AgentCapabilitiesResponse:
        settings = self.settings
        if not settings.agent_enabled:
            return AgentCapabilitiesResponse(
                enabled=False,
                configured=False,
                available=False,
                reason_code="AGENT_DISABLED",
            )
        record = self._load_record(settings.agent_capability_file)
        if record is None:
            return self._unavailable("AGENT_NOT_PROBED")
        if (
            record.provider != settings.agent_provider
            or record.endpoint_hash != provider_endpoint_hash(settings.agent_base_url)
            or record.tested_model != settings.agent_model
        ):
            return self._unavailable("AGENT_PROBE_MISMATCH")
        transport_available = settings.agent_transport in record.transport
        websocket_available = (
            settings.agent_transport == "websocket"
            and settings.agent_websocket_enabled
            and record.websocket_verified
        )
        if settings.agent_transport == "websocket" and not websocket_available:
            return self._from_record(
                record, available=False, reason_code="AGENT_TRANSPORT_UNAVAILABLE"
            )
        text_available = (
            record.text == CapabilitySupport.SUPPORTED
            and record.streaming == CapabilitySupport.SUPPORTED
            and transport_available
        )
        return self._from_record(
            record,
            available=text_available,
            reason_code=None if text_available else "AGENT_PROVIDER_UNAVAILABLE",
        )

    def _from_record(
        self,
        record: AgentProbeRecord,
        *,
        available: bool,
        reason_code: str | None,
    ) -> AgentCapabilitiesResponse:
        settings = self.settings
        image_model_matches = record.image_model == (
            settings.agent_image_model or settings.agent_model
        )
        tools_enabled = (
            available
            and settings.agent_tools_enabled
            and record.function_tools == CapabilitySupport.SUPPORTED
        )
        image_generation_available = (
            available
            and settings.agent_image_enabled
            and image_model_matches
            and record.image_generation == CapabilitySupport.SUPPORTED
        )
        return AgentCapabilitiesResponse(
            enabled=True,
            configured=True,
            available=available,
            reason_code=reason_code,
            provider=settings.agent_provider,
            model=settings.agent_model,
            text=available and record.text == CapabilitySupport.SUPPORTED,
            streaming=available and record.streaming == CapabilitySupport.SUPPORTED,
            function_tools=available and record.function_tools == CapabilitySupport.SUPPORTED,
            image_input=(
                available
                and settings.agent_image_input_enabled
                and record.image_input == CapabilitySupport.SUPPORTED
            ),
            image_generation=image_generation_available,
            usage=record.usage == CapabilitySupport.SUPPORTED,
            transports=list(record.transport),
            websocket_declared=record.websocket_declared,
            websocket_verified=record.websocket_verified,
            tools_enabled=tools_enabled,
            tools=(
                [
                    AgentToolCapability(
                        name=tool.name,
                        risk=tool.risk,
                        requiresApproval=tool.requires_approval,
                    )
                    for tool in self.tool_registry.definitions(
                        image_generation_available=image_generation_available
                    )
                ]
                if tools_enabled
                else []
            ),
            maxTurns=settings.agent_max_turns if tools_enabled else 0,
            maxToolCalls=settings.agent_max_tool_calls if tools_enabled else 0,
            maxApprovals=settings.agent_max_approvals if tools_enabled else 0,
        )

    def _unavailable(self, reason_code: str) -> AgentCapabilitiesResponse:
        return AgentCapabilitiesResponse(
            enabled=True,
            configured=True,
            available=False,
            reason_code=reason_code,
            provider=self.settings.agent_provider,
            model=self.settings.agent_model,
        )

    @staticmethod
    def _load_record(path: Path | None) -> AgentProbeRecord | None:
        if path is None:
            return None
        descriptor: int | None = None
        try:
            flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_size > 64 * 1024
            ):
                return None
            with os.fdopen(descriptor, "r", encoding="utf-8") as source:
                descriptor = None
                payload = source.read(64 * 1024 + 1)
            if len(payload) > 64 * 1024:
                return None
            return AgentProbeRecord.model_validate_json(payload)
        except (OSError, UnicodeError, ValidationError):
            return None
        finally:
            if descriptor is not None:
                os.close(descriptor)
