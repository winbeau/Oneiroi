from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class GatewaySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ONEIROI_GATEWAY_",
        extra="ignore",
    )

    environment: str = "development"
    database_url: str = "postgresql+asyncpg://oneiroi:oneiroi-local@127.0.0.1:5432/oneiroi"
    persistence_enabled: bool = False
    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_leases_enabled: bool = False
    redis_job_streams_enabled: bool = False
    redis_runner_backend_enabled: bool = False
    redis_lease_ttl_seconds: float = Field(default=300, gt=10, le=86_400)
    compute_idle_ttl_seconds: float = Field(default=86_400, gt=0, le=604_800)
    runner_command_timeout_seconds: float = Field(default=900, gt=0, le=3_600)
    runner_job_timeout_seconds: float = Field(default=7_200, gt=0, le=86_400)
    storage_root: Path = Path(".data/storage")
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    nvml_inventory_enabled: bool = False
    gpu_allowlist: str = ""
    gpu_minimum_vram_mib: int = Field(default=70_000, ge=0)
    gpu_idle_vram_threshold_mib: int = Field(default=2_048, ge=0)
    runner_heartbeat_timeout_seconds: float = Field(default=30, gt=0, le=300)
    service_public_key_file: Path | None = None
    service_assertion_issuer: str = "oneiroi-pi-bff"
    service_assertion_audience: str = "oneiroi-h100-gateway"
    service_assertion_clock_skew_seconds: float = Field(default=120, ge=0, le=300)
    gpu_server_enabled: bool = False
    gpu_server_base_url: str = "http://127.0.0.1:8300"
    gpu_server_service_token: SecretStr | None = None
    gpu_server_request_timeout_seconds: float = Field(default=7_200, gt=0, le=86_400)
    gpu_server_poll_seconds: float = Field(default=0.5, gt=0, le=30)
    gpu_server_mapping_ttl_seconds: int = Field(default=86_400, ge=300, le=604_800)
    agent_enabled: bool = False
    agent_provider: Literal["openai-responses"] = "openai-responses"
    agent_api_key: SecretStr | None = None
    agent_base_url: str = ""
    agent_model: str = "gpt-5.6-sol"
    # Dedicated DeepSeek-backed prompt enhancement. The operator fills url/key in .env.
    prompt_enhance_enabled: bool = False
    prompt_enhance_base_url: str = "https://api.deepseek.com"
    prompt_enhance_api_key: SecretStr | None = None
    prompt_enhance_model: str = "deepseek-chat"
    # Fast model used for automatic conversation titles (e.g. deepseek-v4-flash).
    prompt_enhance_title_model: str = "deepseek-v4-flash"
    prompt_enhance_timeout_seconds: float = Field(default=45, gt=1, le=300)
    agent_review_model: str = ""
    agent_reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh"] = "xhigh"
    agent_store: Literal[False] = False
    agent_transport: Literal["sse", "websocket"] = "sse"
    agent_websocket_enabled: bool = False
    agent_provider_websocket_declared: bool = True
    agent_connect_timeout_seconds: float = Field(default=10, gt=0, le=120)
    agent_stream_timeout_seconds: float = Field(default=180, gt=0, le=1_800)
    agent_max_run_seconds: float = Field(default=300, gt=0, le=3_600)
    agent_max_output_tokens: int = Field(default=4_000, ge=1, le=100_000)
    agent_max_events_per_run: int = Field(default=1_000, ge=10, le=10_000)
    agent_tools_enabled: bool = False
    agent_max_turns: int = Field(default=8, ge=1, le=16)
    agent_max_tool_calls: int = Field(default=12, ge=1, le=32)
    agent_max_approvals: int = Field(default=3, ge=1, le=8)
    agent_approval_ttl_seconds: int = Field(default=600, ge=30, le=3_600)
    agent_execution_lease_seconds: int = Field(default=30, ge=5, le=300)
    agent_execution_lease_renew_seconds: int = Field(default=10, ge=1, le=60)
    agent_max_input_images: int = Field(default=4, ge=0, le=8)
    agent_max_image_bytes: int = Field(default=20 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    agent_max_image_pixels: int = Field(default=33_554_432, ge=1, le=100_000_000)
    agent_max_image_edge: int = Field(default=8_192, ge=64, le=16_384)
    agent_image_tool_timeout_seconds: float = Field(default=30, gt=1, le=1_800)
    agent_max_retries: int = Field(default=2, ge=0, le=5)
    agent_max_retry_delay_seconds: float = Field(default=4, ge=0, le=60)
    agent_capability_file: Path | None = None
    agent_image_input_enabled: bool = False
    agent_image_enabled: bool = False
    # Image generation uses its own provider/model (e.g. gpt-image-2). The API key
    # and base URL are independent of the text agent; keep them in the deployment
    # host's runtime config. Image requests time out at 30s (generation ~22s).
    agent_image_model: str = "gpt-image-2"
    agent_image_api_key: SecretStr | None = None
    agent_image_base_url: str = ""
    agent_image_timeout_seconds: float = Field(default=30, gt=1, le=300)
    agent_image_mode: Literal["responses-tool"] = "responses-tool"
    ltx_git_commit: str = ""
    ltx_distilled_checkpoint_path: str = ""
    ltx_distilled_checkpoint_sha256: str = ""
    ltx_dev_checkpoint_path: str = ""
    ltx_dev_checkpoint_sha256: str = ""
    ltx_distilled_lora_path: str = ""
    ltx_distilled_lora_sha256: str = ""
    ltx_upsampler_path: str = ""
    ltx_upsampler_sha256: str = ""
    ltx_gemma_root: str = ""
    ltx_gemma_revision: str = ""

    @model_validator(mode="after")
    def validate_enabled_integrations(self) -> "GatewaySettings":
        if self.gpu_server_enabled and self.gpu_server_service_token is None:
            raise ValueError("ONEIROI_GATEWAY_GPU_SERVER_SERVICE_TOKEN is required")
        if self.agent_base_url:
            parsed = urlsplit(self.agent_base_url)
            try:
                _ = parsed.port
            except ValueError as exc:
                raise ValueError("ONEIROI_GATEWAY_AGENT_BASE_URL must use a valid port") from exc
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "ONEIROI_GATEWAY_AGENT_BASE_URL must be a credential-free HTTPS URL"
                )
        if self.agent_enabled:
            if self.agent_api_key is None or not self.agent_api_key.get_secret_value().strip():
                raise ValueError("ONEIROI_GATEWAY_AGENT_API_KEY is required")
            if not self.agent_base_url:
                raise ValueError("ONEIROI_GATEWAY_AGENT_BASE_URL is required")
            if not self.agent_model.strip() or any(char in self.agent_model for char in "\r\n"):
                raise ValueError("ONEIROI_GATEWAY_AGENT_MODEL is required")
        if self.agent_transport == "websocket" and not self.agent_websocket_enabled:
            raise ValueError(
                "ONEIROI_GATEWAY_AGENT_TRANSPORT=websocket requires the explicit "
                "WebSocket canary flag"
            )
        if self.agent_tools_enabled and not self.agent_enabled:
            raise ValueError("Agent tools require ONEIROI_GATEWAY_AGENT_ENABLED=true")
        if (self.agent_image_input_enabled or self.agent_image_enabled) and not self.agent_enabled:
            raise ValueError("Agent image flags require ONEIROI_GATEWAY_AGENT_ENABLED=true")
        if self.agent_stream_timeout_seconds > self.agent_max_run_seconds:
            raise ValueError("Agent stream timeout cannot exceed the maximum run timeout")
        if self.agent_execution_lease_renew_seconds >= self.agent_execution_lease_seconds:
            raise ValueError("Agent execution lease renewal must be shorter than the lease")
        return self

    @property
    def allowed_gpu_ids(self) -> frozenset[str] | None:
        values = frozenset(item.strip() for item in self.gpu_allowlist.split(",") if item.strip())
        return values or None


@lru_cache
def get_settings() -> GatewaySettings:
    return GatewaySettings()
