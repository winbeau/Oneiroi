# Durable GPT Agent runtime

Stages B and C add a server-side prompt assistant and durable Agent state to the Gateway. The provider remains disabled by default, and the browser and Pi BFF never receive provider credentials, provider endpoint overrides, or raw provider events.

## Runtime boundary

```text
Browser
  -> Pi BFF explicit Agent route allowlist
  -> Gateway AgentRouter
  -> AgentRuntime
  -> AgentRepository (PostgreSQL in persistent mode)
  -> AgentProvider
```

The runtime is deliberately narrow:

- it can read the current owner's Conversation, draft snapshot, and selected Asset metadata;
- it asks the provider for a bounded structured response;
- it persists an editable `DraftProposal` for user review;
- it does not apply the proposal, submit a video Job, generate an image, or execute a tool in Stages B/C;
- it exposes no shell, SQL, filesystem, arbitrary HTTP, internal-network, or dynamic code execution capability;
- raw reasoning and provider events are not persisted or returned to the browser.

If the provider is disabled or has not passed the capability gate, run creation fails closed with `AGENT_NOT_CONFIGURED`. Existing Conversation, Asset, Job, and Compute APIs remain available.

## API

The BFF allowlists each route explicitly; there is no `/v1/agent/{path:path}` proxy.

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/v1/agent/runs` | Create an idempotent run; requires `Idempotency-Key` |
| `GET` | `/v1/agent/runs/{run_id}` | Read the owner-bound run snapshot |
| `POST` | `/v1/agent/runs/{run_id}/cancel` | Cancel an incomplete run idempotently |
| `GET` | `/v1/agent/runs/{run_id}/events` | Replay and follow durable SSE events |
| `GET` | `/v1/agent/threads/{thread_id}/messages` | Read bounded thread history |
| `GET` | `/v1/conversations/{conversation_id}/agent/thread` | Resolve the Conversation's Agent thread |

The BFF applies a smaller Agent JSON body limit than the general API limit. It forwards only the existing trusted service assertion plus the allowlisted `Idempotency-Key` and `Last-Event-ID` headers; browser `Authorization` and `Cookie` headers are not forwarded upstream.

Cross-owner resource access is hidden as `404`.

## Canonical state

Migration `0002_agent_runtime` creates:

- `agent_threads`;
- `agent_runs`;
- `agent_messages`;
- `agent_tool_calls`;
- `agent_approvals`;
- `agent_events`.

PostgreSQL is canonical whenever persistence is enabled. The in-memory repository is retained only for deterministic development and unit tests.

Database constraints enforce:

- owner-bound Conversation/thread/run/message/event relationships;
- a run's thread and Conversation belonging to the same owner and the same Conversation;
- one idempotency key per owner;
- one active run per owner through a partial unique index covering all non-terminal states;
- unique message and event sequence numbers within their parent;
- tool-call and approval ownership relationships reserved for Stage D.

State-changing repository methods lock the current run row and compare its latest status with explicit expected states before updating. A stale worker therefore cannot overwrite a concurrent cancellation or terminal completion. The same check protects streamed event append and assistant-message completion.

## Run states and recovery

Stages B/C actively use:

```text
queued -> streaming -> completed
queued/streaming -> cancelling -> cancelled
queued/streaming/waiting_approval/recovering -> failed
```

`waiting_approval` and `executing_tool` are persisted in the schema for the controlled Stage D runtime, but Stages B/C never enter those states during normal execution.

At Gateway startup, every incomplete persisted run is resolved deterministically:

- `cancelling` becomes `cancelled`;
- every other incomplete state, including a pre-Stage-D `waiting_approval`, becomes `failed` with `AGENT_RECOVERY_REQUIRED`.

This policy prevents an interrupted run from holding the per-owner execution slot indefinitely. Stage D may replace the `waiting_approval` recovery behavior only after durable approval consumption is implemented.

## Durable SSE

Every externally visible lifecycle event is committed before it is streamed. Event IDs are PostgreSQL row IDs and event sequence numbers are unique within a run.

Clients may reconnect with `Last-Event-ID`. The Gateway:

1. verifies owner access to the run;
2. reads events after the cursor in pages of at most 200;
3. emits heartbeats while a non-terminal run is idle;
4. closes the stream after all events for a terminal run have been replayed.

The stream exposes bounded user-visible deltas, proposal snapshots, status, and stable error codes. It does not expose raw provider payloads or chain-of-thought.

## Limits and failure behavior

- one active run per owner, enforced in both runtime logic and PostgreSQL;
- `Idempotency-Key` is required, bounded, and rejected when reused with different input;
- selected input assets are owner-checked and limited by `ONEIROI_GATEWAY_AGENT_MAX_INPUT_IMAGES`;
- provider output text is bounded to 20,000 characters;
- provider source events are bounded by `ONEIROI_GATEWAY_AGENT_MAX_EVENTS_PER_RUN` (default `1000`);
- message reads are limited to 100 per request;
- SSE persistence reads are paged at 200 events;
- malformed structured output fails with `AGENT_OUTPUT_INVALID` without echoing the provider body;
- provider errors use the normalized Stage A error mapping;
- cancellation wins over concurrent delta append or completion and terminates as `cancelled`, not `failed`.

## Validation evidence

Repository tests cover owner isolation, idempotency reuse, active-run limits, stale-state compare-and-swap, bounded event reads, cancellation races, invalid structured output, event limits, restart recovery, and durable SSE replay.

The loopback PostgreSQL integration suite additionally verifies:

- migration downgrade and upgrade;
- Agent state surviving Gateway recreation;
- cross-repository concurrent create protection;
- SQL compare-and-swap rejection;
- owner and thread/Conversation foreign-key relationships;
- recovery of `waiting_approval` releasing the active-run slot.

These tests use the deterministic fake provider. They do not claim a real provider canary, real Authentik dual-user browser acceptance, a real gpu-server Runner, or production deployment.

## Rollback

1. Set `ONEIROI_GATEWAY_AGENT_ENABLED=false` so new runs fail closed.
2. Allow active requests to terminate or cancel them through the owner-bound API.
3. Keep the Agent tables in place for a code-only rollback; they do not alter existing Conversation, Asset, Job, or Compute API contracts.
4. Only when Agent data is intentionally disposable, run `alembic downgrade 0001_dynamic_backend` to drop the Agent tables. This is destructive and must not be done as an automatic production rollback.

No production service, Cloudflare configuration, or gpu-server runtime is changed by Stages B/C.
