import asyncio
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request, status
from fastapi.responses import JSONResponse

from oneiroi_common.api import ServiceHealth
from oneiroi_common.identity import SERVICE_ASSERTION_HEADER
from oneiroi_common.jobs import QueueTier
from oneiroi_gateway.agent.openai_responses import OpenAIResponsesProvider
from oneiroi_gateway.agent.prompt_enhance import PromptEnhancer
from oneiroi_gateway.agent.protocol import AgentProvider
from oneiroi_gateway.agent.registry import ToolRegistry, builtin_tool_registry
from oneiroi_gateway.agent.runtime import AgentRuntime
from oneiroi_gateway.db.session import create_engine, create_session_factory
from oneiroi_gateway.gpu_server import (
    GpuServerClient,
    GpuServerComputeBackend,
    GpuServerInventoryProvider,
    GpuServerJobExecutor,
    GpuServerLeaseStore,
)
from oneiroi_gateway.redis.control_streams import RedisDirectedStreams
from oneiroi_gateway.redis.leases import RedisLeaseStore
from oneiroi_gateway.repositories.agent import AgentRepository, InMemoryAgentRepository
from oneiroi_gateway.repositories.compute import SqlComputeStateRepository
from oneiroi_gateway.repositories.sql_agent import SqlAgentRepository
from oneiroi_gateway.repositories.sql_studio import SqlStudioRepository
from oneiroi_gateway.repositories.studio import InMemoryStudioRepository, StudioRepository
from oneiroi_gateway.routes.agent import create_agent_router
from oneiroi_gateway.routes.assets import create_asset_router
from oneiroi_gateway.routes.compute import create_compute_router
from oneiroi_gateway.routes.conversations import create_conversation_router
from oneiroi_gateway.routes.jobs import create_job_router
from oneiroi_gateway.routes.uploads import create_upload_router
from oneiroi_gateway.service_auth import (
    ServiceAssertionValidator,
    ServiceAuthConfigurationError,
    ServiceAuthenticationError,
)
from oneiroi_gateway.services.agent_capabilities import AgentCapabilityService
from oneiroi_gateway.services.artifact_service import ArtifactService
from oneiroi_gateway.services.capabilities import CapabilityService
from oneiroi_gateway.services.compute_sessions import (
    ComputeSessionService,
    UnavailableComputeBackend,
)
from oneiroi_gateway.services.gpu_inventory import (
    GpuInventoryService,
    InMemoryInventoryProvider,
    NvmlInventoryProvider,
)
from oneiroi_gateway.services.job_dispatcher import (
    InMemoryJobDispatcher,
    JobDispatcher,
    RedisJobDispatcher,
)
from oneiroi_gateway.services.job_execution import JobExecutor, RedisJobExecutor
from oneiroi_gateway.services.job_scheduler import JobScheduler
from oneiroi_gateway.services.job_service import JobService
from oneiroi_gateway.services.pipeline_profiles import PipelineProfileCatalog
from oneiroi_gateway.services.runner_backend import RedisComputeBackend
from oneiroi_gateway.services.runner_heartbeats import RunnerHeartbeatMonitor
from oneiroi_gateway.settings import GatewaySettings, get_settings

__version__ = "0.1.0"


def _build_prompt_enhancer(app_settings: GatewaySettings) -> PromptEnhancer | None:
    if not app_settings.prompt_enhance_enabled:
        return None
    key = app_settings.prompt_enhance_api_key
    if key is None or not key.get_secret_value().strip():
        return None
    return PromptEnhancer(
        base_url=app_settings.prompt_enhance_base_url,
        api_key=key.get_secret_value(),
        model=app_settings.prompt_enhance_model,
        title_model=app_settings.prompt_enhance_title_model,
        timeout_seconds=app_settings.prompt_enhance_timeout_seconds,
    )


def create_app(
    settings: GatewaySettings | None = None,
    *,
    inventory_service: GpuInventoryService | None = None,
    compute_session_service: ComputeSessionService | None = None,
    capability_service: CapabilityService | None = None,
    agent_capability_service: AgentCapabilityService | None = None,
    agent_repository: AgentRepository | None = None,
    agent_provider: AgentProvider | None = None,
    prompt_enhancer: PromptEnhancer | None = None,
    agent_runtime: AgentRuntime | None = None,
    agent_tool_registry: ToolRegistry | None = None,
    artifact_service: ArtifactService | None = None,
    allow_unprobed_agent_provider_for_tests: bool = False,
    repository: StudioRepository | None = None,
    job_dispatcher: JobDispatcher | None = None,
    job_executor: JobExecutor | None = None,
    job_service: JobService | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    service_validator = ServiceAssertionValidator(
        app_settings.service_public_key_file,
        issuer=app_settings.service_assertion_issuer,
        audience=app_settings.service_assertion_audience,
        clock_skew_seconds=app_settings.service_assertion_clock_skew_seconds,
    )
    managed_compute_service = compute_session_service is None
    gpu_server_client = (
        GpuServerClient(
            app_settings.gpu_server_base_url,
            app_settings.gpu_server_service_token.get_secret_value(),
            timeout_seconds=app_settings.gpu_server_request_timeout_seconds,
        )
        if app_settings.gpu_server_enabled and app_settings.gpu_server_service_token is not None
        else None
    )
    if inventory_service is None:
        provider = (
            GpuServerInventoryProvider(gpu_server_client)
            if gpu_server_client is not None
            else NvmlInventoryProvider(
                allowlist=app_settings.allowed_gpu_ids,
                minimum_vram_mib=app_settings.gpu_minimum_vram_mib,
                idle_vram_threshold_mib=app_settings.gpu_idle_vram_threshold_mib,
            )
            if app_settings.nvml_inventory_enabled
            else InMemoryInventoryProvider()
        )
        inventory_service = GpuInventoryService(provider)
    if (
        not app_settings.gpu_server_enabled
        and app_settings.redis_runner_backend_enabled
        and not app_settings.redis_leases_enabled
    ):
        raise RuntimeError("Redis Runner backend requires Redis GPU leases")
    redis_streams = (
        RedisDirectedStreams(app_settings.redis_url)
        if not app_settings.gpu_server_enabled
        and (app_settings.redis_runner_backend_enabled or app_settings.redis_job_streams_enabled)
        else None
    )
    gpu_server_leases = None
    if compute_session_service is None:
        gpu_server_leases = (
            GpuServerLeaseStore(
                gpu_server_client,
                app_settings.redis_url,
                mapping_ttl_seconds=app_settings.gpu_server_mapping_ttl_seconds,
            )
            if gpu_server_client is not None
            else None
        )
        compute_backend = (
            GpuServerComputeBackend()
            if gpu_server_leases is not None
            else RedisComputeBackend(
                redis_streams,
                PipelineProfileCatalog.from_settings(app_settings),
                command_timeout_seconds=app_settings.runner_command_timeout_seconds,
            )
            if app_settings.redis_runner_backend_enabled and redis_streams is not None
            else UnavailableComputeBackend()
        )
        compute_session_service = ComputeSessionService(
            inventory_service,
            compute_backend,
            leases=(
                gpu_server_leases
                or (
                    RedisLeaseStore(app_settings.redis_url)
                    if app_settings.redis_leases_enabled
                    else None
                )
            ),
            lease_ttl_seconds=app_settings.redis_lease_ttl_seconds,
            idle_ttl_seconds=app_settings.compute_idle_ttl_seconds,
        )
    capability_service = capability_service or CapabilityService()
    agent_tool_registry = agent_tool_registry or builtin_tool_registry(
        image_timeout_seconds=app_settings.agent_image_tool_timeout_seconds
    )
    agent_capability_service = agent_capability_service or AgentCapabilityService(
        app_settings, agent_tool_registry
    )
    database_engine = None
    database_sessions = None
    if repository is None:
        if app_settings.persistence_enabled:
            database_engine = create_engine(app_settings.database_url)
            database_sessions = create_session_factory(database_engine)
            repository = SqlStudioRepository(database_sessions)
        else:
            repository = InMemoryStudioRepository()
    if managed_compute_service and database_sessions is not None:
        compute_session_service.state_repository = SqlComputeStateRepository(database_sessions)
    if agent_repository is None:
        agent_repository = (
            SqlAgentRepository(database_sessions)
            if database_sessions is not None
            else InMemoryAgentRepository()
        )
    artifacts = artifact_service or ArtifactService(
        repository,
        app_settings.storage_root,
        max_upload_bytes=app_settings.max_upload_bytes,
        max_image_pixels=app_settings.agent_max_image_pixels,
        max_image_edge=app_settings.agent_max_image_edge,
    )
    agent_provider_injected = agent_provider is not None
    agent_capabilities = agent_capability_service.get()
    injected_provider_available = (
        agent_provider_injected
        and app_settings.agent_enabled
        and (agent_capabilities.available or allow_unprobed_agent_provider_for_tests)
    )
    if agent_provider_injected and not injected_provider_available:
        agent_provider = None
    if agent_provider is None and agent_capabilities.available:
        assert app_settings.agent_api_key is not None
        agent_provider = OpenAIResponsesProvider(
            app_settings.agent_base_url,
            app_settings.agent_api_key.get_secret_value(),
            model=app_settings.agent_model,
            reasoning_effort=app_settings.agent_reasoning_effort,
            image_model=app_settings.agent_image_model or None,
            image_base_url=app_settings.agent_image_base_url or None,
            image_api_key=(
                app_settings.agent_image_api_key.get_secret_value()
                if app_settings.agent_image_api_key is not None
                else None
            ),
            image_timeout_seconds=app_settings.agent_image_timeout_seconds,
            websocket_declared=app_settings.agent_provider_websocket_declared,
            connect_timeout_seconds=app_settings.agent_connect_timeout_seconds,
            stream_timeout_seconds=app_settings.agent_stream_timeout_seconds,
            max_run_seconds=app_settings.agent_max_run_seconds,
            max_retries=app_settings.agent_max_retries,
            max_retry_delay_seconds=app_settings.agent_max_retry_delay_seconds,
            max_image_bytes=app_settings.agent_max_image_bytes,
        )
    agent_runtime = agent_runtime or AgentRuntime(
        agent_repository,
        repository,
        agent_provider,
        app_settings,
        agent_tool_registry,
        tools_available=(
            agent_capabilities.function_tools
            or (injected_provider_available and allow_unprobed_agent_provider_for_tests)
        ),
        artifacts=artifacts,
        image_input_available=(
            agent_capabilities.image_input
            or (
                injected_provider_available
                and allow_unprobed_agent_provider_for_tests
                and bool(getattr(agent_provider, "image_input", False))
                and app_settings.agent_image_input_enabled
            )
        ),
        image_generation_available=(
            agent_capabilities.image_generation
            or (
                injected_provider_available
                and allow_unprobed_agent_provider_for_tests
                and bool(getattr(agent_provider, "image_generation", False))
                and app_settings.agent_image_enabled
            )
        ),
    )
    if job_dispatcher is None:
        if redis_streams is not None and (
            app_settings.redis_job_streams_enabled or app_settings.redis_runner_backend_enabled
        ):
            job_dispatcher = RedisJobDispatcher(redis_streams)
        else:
            job_dispatcher = InMemoryJobDispatcher()
    if job_executor is None and gpu_server_client is not None:
        if gpu_server_leases is None:
            raise RuntimeError("gpu-server jobs require the gpu-server compute adapter")
        job_executor = GpuServerJobExecutor(
            gpu_server_client,
            gpu_server_leases,
            poll_seconds=app_settings.gpu_server_poll_seconds,
        )
    elif job_executor is None and app_settings.redis_runner_backend_enabled:
        assert redis_streams is not None
        job_executor = RedisJobExecutor(
            redis_streams,
            timeout_seconds=app_settings.runner_job_timeout_seconds,
        )
    if job_service is None:
        job_service = JobService(
            repository,
            compute_session_service,
            capability_service,
            JobScheduler(compute_session_service),
            job_dispatcher,
            artifacts,
            job_executor,
        )
    heartbeat_monitor = (
        RunnerHeartbeatMonitor(
            app_settings.redis_url,
            compute_session_service,
            timeout_seconds=app_settings.runner_heartbeat_timeout_seconds,
        )
        if app_settings.redis_runner_backend_enabled and not app_settings.gpu_server_enabled
        else None
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await compute_session_service.restore()
        await agent_runtime.recover_incomplete()
        await job_service.restore_inflight()
        heartbeat_stop = asyncio.Event()
        heartbeat_task = (
            asyncio.create_task(
                heartbeat_monitor.run(heartbeat_stop),
                name="runner-heartbeat-monitor",
            )
            if heartbeat_monitor is not None
            else None
        )
        try:
            yield
        finally:
            if heartbeat_task is not None and heartbeat_monitor is not None:
                await heartbeat_monitor.stop(heartbeat_task, heartbeat_stop)
            await agent_runtime.close()
            await job_service.close()
            await compute_session_service.close()
            if redis_streams is not None:
                await redis_streams.close()
            if database_engine is not None:
                await database_engine.dispose()

    app = FastAPI(
        title="Oneiroi Studio Gateway",
        version=__version__,
        docs_url="/docs" if app_settings.environment == "development" else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def require_private_identity(request: Request, call_next):
        protected = request.url.path.startswith("/v1/") and not request.url.path.startswith(
            "/v1/system/"
        )
        if app_settings.environment != "development" and protected:
            user = request.headers.get("X-Oneiroi-User", "").strip()
            assertion = request.headers.get(SERVICE_ASSERTION_HEADER, "")
            try:
                asserted_owner = service_validator.validate(assertion)
            except ServiceAuthConfigurationError:
                return JSONResponse(
                    {"detail": "AUTHENTICATION_NOT_CONFIGURED"},
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            except ServiceAuthenticationError:
                return JSONResponse(
                    {"detail": "AUTHENTICATION_REQUIRED"},
                    status_code=status.HTTP_401_UNAUTHORIZED,
                )
            if not user or user != asserted_owner:
                return JSONResponse(
                    {"detail": "AUTHENTICATION_REQUIRED"},
                    status_code=status.HTTP_401_UNAUTHORIZED,
                )
        return await call_next(request)

    system_router = APIRouter(tags=["system"])

    @system_router.get("/healthz", response_model=ServiceHealth)
    async def healthz() -> ServiceHealth:
        return ServiceHealth(service="gateway", version=__version__)

    @system_router.get("/v1/system/queues")
    async def queue_catalog() -> dict[str, list[str]]:
        return {"queues": [tier.value for tier in QueueTier]}

    app.include_router(system_router)
    app.state.database_engine = database_engine
    app.state.redis_streams = redis_streams
    app.state.repository = repository
    app.state.job_service = job_service
    app.state.agent_capability_service = agent_capability_service
    app.state.agent_repository = agent_repository
    app.state.agent_runtime = agent_runtime
    app.include_router(
        create_agent_router(
            agent_capability_service,
            agent_runtime,
            enhancer=prompt_enhancer or _build_prompt_enhancer(app_settings),
        )
    )
    app.include_router(
        create_compute_router(inventory_service, compute_session_service, capability_service)
    )
    app.include_router(create_conversation_router(repository, artifacts))
    app.include_router(create_asset_router(repository, artifacts))
    app.include_router(create_upload_router(artifacts))
    app.include_router(create_job_router(job_service))
    return app


app = create_app()
