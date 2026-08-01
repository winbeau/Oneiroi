# GPT Agent provider configuration and probe

Stage A adds a disabled-by-default OpenAI-compatible Responses API adapter to the H100 Gateway. The browser and Pi BFF never receive the provider credential, base URL override, or raw provider events.

## Reference mapping

The reviewed non-secret reference configuration maps to Gateway settings as follows:

| Reference | Gateway setting |
|---|---|
| OpenAI-compatible Responses API | `ONEIROI_GATEWAY_AGENT_PROVIDER=openai-responses` |
| `gpt-5.6-sol` | `ONEIROI_GATEWAY_AGENT_MODEL=gpt-5.6-sol` |
| `xhigh` reasoning | `ONEIROI_GATEWAY_AGENT_REASONING_EFFORT=xhigh` |
| response storage disabled | `ONEIROI_GATEWAY_AGENT_STORE=false` |
| `https://api.selab.top/v1` | `ONEIROI_GATEWAY_AGENT_BASE_URL=https://api.selab.top/v1` |
| WebSocket declared | `ONEIROI_GATEWAY_AGENT_PROVIDER_WEBSOCKET_DECLARED=true` |

The runtime remains on `ONEIROI_GATEWAY_AGENT_TRANSPORT=sse`. A provider declaration is not proof of WebSocket capability; WebSocket also requires the explicit canary flag and a probe record with `websocketVerified=true`.

## Required settings

Agent remains off unless all of the following are supplied in the restricted Gateway runtime:

```text
ONEIROI_GATEWAY_AGENT_ENABLED=true
ONEIROI_GATEWAY_AGENT_API_KEY=<runtime secret>
ONEIROI_GATEWAY_AGENT_BASE_URL=https://api.selab.top/v1
ONEIROI_GATEWAY_AGENT_MODEL=gpt-5.6-sol
ONEIROI_GATEWAY_AGENT_CAPABILITY_FILE=/restricted/path/agent-capabilities.json
```

When enabled, configuration validation rejects a missing/empty key, a non-HTTPS or credential-bearing URL, and an empty model. `store=true` is invalid. Do not place the key in Vite variables, BFF configuration, command-line arguments, repository files, OpenAPI, or probe output.

## Capability probe

Inject the credential through the restricted Gateway environment, then run:

```bash
uv run python -m oneiroi_gateway.agent.capability_probe \
  --output /restricted/path/agent-capabilities.json
```

The default probe covers:

- text completion and HTTP SSE termination;
- visible text deltas and usage;
- strict function-tool arguments and a stateless tool-result continuation;
- image input;
- the provider WebSocket declaration versus verified transport.

Optional requests are explicit because they may be billable or intentionally fail:

```bash
uv run python -m oneiroi_gateway.agent.capability_probe \
  --output /restricted/path/agent-capabilities.json \
  --include-image-generation \
  --probe-error-format
```

`--include-image-generation` is required before image generation can be marked supported. `--probe-error-format` sends one invalid-model request to inspect the normalized error shape. Deterministic fixture tests cover 401/403, 429, 5xx, timeout/interruption, fragmented SSE, duplicate provider event IDs, and malformed tool arguments without calling a real provider.

The probe writes a `0600` temporary file and atomically renames it. It records capability states, tested text/image models, transport, time, bounded booleans, and a SHA-256 identity of the normalized provider endpoint. It does not record API keys, Authorization headers, the base URL itself, prompts, image bytes, raw provider payloads, or response bodies. Gateway accepts only a regular, non-symlink capability file owned by the Gateway user with mode `0600`; it also rejects oversized records and requires a new probe whenever the endpoint or model changes.

## Capability endpoint

`GET /v1/agent/capabilities` is owner-bound by the existing Gateway service-assertion middleware outside development. It never performs a live provider request.

Fail-closed states include:

- `AGENT_DISABLED` — feature flag is off;
- `AGENT_NOT_PROBED` — capability file is absent or invalid;
- `AGENT_PROBE_MISMATCH` — provider/model differs from the record;
- `AGENT_TRANSPORT_UNAVAILABLE` — WebSocket was declared but not verified;
- `AGENT_PROVIDER_UNAVAILABLE` — core text/stream capability is unsupported.

Image input and image generation remain independently disabled unless both their feature flag and matching probe capability are present.

## Current external blockers

No real provider canary is claimed by repository tests. Before canary activation an operator must:

1. migrate and rotate the plaintext reference credential into restricted Gateway runtime configuration;
2. run the non-echoing capability probe against the configured provider;
3. review the generated non-secret record, especially image model/return mode and WebSocket verification;
4. keep all Agent flags off until that review passes.

## Rollback

Set `ONEIROI_GATEWAY_AGENT_ENABLED=false` and leave image/WebSocket flags false. Stage A adds no database migration and does not change Conversation, Asset, Job, Compute, identity, or production runtime behavior.
