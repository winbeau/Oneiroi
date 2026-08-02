# Durable controlled GPT Agent runtime

Stages B–D add an owner-bound, durable prompt assistant with a strict server-side tool registry and one-time approval framework. The Agent and tool feature flags remain disabled by default. The browser and Pi BFF never receive provider credentials, provider endpoint overrides, internal storage paths, raw provider events, or hidden reasoning.

## Runtime boundary

```text
Browser
  -> Pi BFF explicit Agent route allowlist
  -> Gateway AgentRouter
  -> AgentRuntime
  -> AgentRepository (PostgreSQL in persistent mode)
  -> ToolRegistry -> existing owner-bound Studio repositories/services
  -> AgentProvider
```

The provider may propose only tools registered by the Gateway. The model cannot register a tool, choose an owner, replace arguments during approval, provide a filesystem path, or authorize an operation. Tool handlers receive the authenticated owner from server context and re-read owner-bound resources through existing repositories.

If the provider is disabled or has not passed the capability gate, run creation fails closed with `AGENT_NOT_CONFIGURED`. If function tools are unsupported by the endpoint/model capability record, the toolset remains unavailable even when `ONEIROI_GATEWAY_AGENT_TOOLS_ENABLED=true`.

## API

The BFF allowlists every Agent route explicitly; there is no `/v1/agent/{path:path}` proxy.

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/v1/agent/runs` | Create an idempotent run; requires `Idempotency-Key` |
| `GET` | `/v1/agent/runs/{run_id}` | Read the owner-bound run snapshot |
| `POST` | `/v1/agent/runs/{run_id}/cancel` | Cancel an incomplete run idempotently |
| `GET` | `/v1/agent/runs/{run_id}/events` | Replay and follow durable SSE events |
| `GET` | `/v1/agent/threads/{thread_id}/messages` | Read bounded thread history |
| `GET` | `/v1/conversations/{conversation_id}/agent/thread` | Resolve the Conversation's Agent thread |
| `POST` | `/v1/agent/tool-calls/{tool_call_id}/approve` | Approve the persisted arguments once |
| `POST` | `/v1/agent/tool-calls/{tool_call_id}/reject` | Reject the persisted call once and continue |

Approve and reject bodies contain only bounded decision metadata (`note` and `clientVersion`). They cannot contain replacement tool arguments. Cross-owner run, thread, tool-call, approval, Asset, Conversation, and Job access is hidden as `404`.

The BFF applies the smaller Agent JSON body limit and forwards only the trusted service assertion plus explicitly allowlisted `Idempotency-Key` and `Last-Event-ID` headers. Browser `Authorization` and `Cookie` headers are not forwarded upstream.

## Registered Stage D tools

`ONEIROI_GATEWAY_AGENT_TOOLS_ENABLED=false` by default. When both the flag and provider function-tool capability are enabled, the built-in registry exposes:

| Tool | Risk | Behavior |
|---|---|---|
| `get_creation_context` | read | Reads the run Conversation, submitted draft snapshot, selected safe Asset metadata, and up to three recent Job snapshots |
| `list_assets` | read | Lists at most 20 owner-bound Asset metadata records with bounded filters |
| `get_asset_metadata` | read | Reads safe metadata for one owner-bound Asset |
| `get_job_snapshot` | read | Reads a bounded owner-bound Job snapshot |
| `propose_draft_patch` | proposal | Returns a validated candidate and never mutates the stored/browser draft or creates a Job |

Safe results omit storage paths, internal hosts, raw backend/provider payloads, credentials, and exception stacks. Asset titles, Job errors, draft fields, prior messages, image/OCR content, and tool results remain untrusted prompt data.

Stage D implements the approval engine for `write`, `costly`, and `destructive` risks and verifies it with injected deterministic tools. No production costly or destructive built-in is registered yet. Image generation, Asset creation, video Job creation/retry/cancel, and their real side-effect reconciliation belong to later stages and are not claimed here.

The registry enforces strict Pydantic/JSON Schema input and output models, per-tool call limits, bounded handler timeouts, a 32 KiB canonical argument limit, a 64 KiB result limit, and a 64 KiB provider tool-argument stream limit. Unknown tools, extra fields, malformed arguments, oversized payloads, and invalid results fail without executing a handler.

## Run loop and budgets

The bounded loop is:

```text
create run
  -> persist user message
  -> stream provider turn
  -> no tool: validate structured response -> completed
  -> read/proposal tool: persist -> execute -> persist result -> continue provider
  -> approval tool: persist call/approval -> waiting_approval -> stop current task
  -> approve: atomically consume -> execute once -> continue provider
  -> reject: persist rejection -> continue provider
```

Configured defaults are:

- at most 8 provider turns per run;
- at most 12 tool calls and 3 approvals per run;
- approval TTL of 600 seconds;
- maximum run time of 300 seconds;
- at most 1,000 source provider events;
- at most 20,000 characters of final text;
- one non-terminal run per owner, enforced by PostgreSQL and the runtime.

Budget exhaustion terminates with a stable error and does not continue an autonomous loop.

## Durable approval and exactly-once claim

An approval is bound to owner, run, tool call, tool name/version, canonical argument SHA-256, risk/cost metadata, and expiration time. Approval decisions never accept new arguments.

The repository locks the approval, tool call, and run rows in one transaction. The first valid approve changes the approval to `consumed`, changes the tool call to `approved`, assigns the run execution lease, and returns `claimed=true`. Concurrent or repeated approve requests return the current snapshot with `claimed=false`; they do not launch a second handler. Reject and expiration are likewise durable and idempotent.

Provider replay is bound to the provider call ID plus canonical argument hash. Reusing a call ID with different tool name or arguments fails closed. A persisted `approved` or `running` costly operation is never replayed after an unknown interruption.

## Canonical state and database constraints

Migration `0002_agent_runtime` creates:

- `agent_threads`;
- `agent_runs`;
- `agent_messages`;
- `agent_tool_calls`;
- `agent_approvals`;
- `agent_events`.

Migration `0003_agent_execution_lease` adds `executor_id` and `execution_lease_expires_at` to `agent_runs` for multi-Gateway execution fencing.

PostgreSQL is canonical whenever persistence is enabled. The in-memory repository is retained only for deterministic development and unit tests. Composite foreign keys bind owner, Conversation, thread, run, message, event, tool call, and approval. A partial unique index allows only one non-terminal run per owner.

All worker state writes—run transitions, durable deltas, final messages, tool proposal/start/finish, and failure/cancellation completion—lock the current row and atomically verify both expected status and the current unexpired execution lease. Ordinary run-state updates cannot overwrite a lease renewed by another transaction. An expired lease cannot be renewed; it must be claimed through recovery, preventing a paused old worker from resuming after takeover.

## Execution leases, cancellation, and recovery

Each runtime instance uses a random executor ID. The default execution lease is 30 seconds and renews every 10 seconds; renewal must be shorter than the lease. Run creation and approval continuation establish the lease before scheduling work.

At Gateway startup:

1. valid pending approvals are preserved and their TTL tasks are restored;
2. only runs with no lease or an expired lease are considered recoverable;
3. recovery claims and renews a fenced lease before changing state;
4. `approved` or `running` tools are marked `AGENT_TOOL_RECOVERY_REQUIRED` and are not replayed;
5. stale `cancelling` runs become `cancelled`; other stale incomplete runs become `failed / AGENT_RECOVERY_REQUIRED`;
6. a healthy Gateway's unexpired run is left untouched during restart, rollout, or scale-out of another Gateway.

Approval handoff is safe when the user approves before the provider task has fully returned: the approved continuation is attached to the existing task and starts after that task exits. Task cleanup is identity-checked so an old callback cannot remove the new continuation task.

Cross-Gateway cancellation changes the run to `cancelling`. An approved-but-not-started tool is failed before the terminal cancellation event. If a handler is already `running`, cancellation does not falsely claim rollback; the run remains `cancelling` until the bounded handler settles, then records the tool result/failure before `agent.run.cancelled`. If the Gateway disappears, lease-based recovery records the result as unknown and does not replay the side effect.

## Durable SSE

Every externally visible lifecycle event is committed before it is streamed. Event IDs are PostgreSQL row IDs and event sequence numbers are unique within a run.

Clients may reconnect with `Last-Event-ID`. The Gateway owner-checks the run, reads events in pages of at most 200, emits heartbeats while idle, and closes after terminal replay. The stream exposes bounded user-visible deltas, proposal/tool/approval snapshots, status, and stable error codes. It does not expose raw provider payloads or chain-of-thought.

## Security properties

- server instructions explicitly treat all user and resource content as untrusted;
- no shell, Python, `eval`/`exec`, arbitrary SQL, filesystem, arbitrary HTTP, URL fetch, internal-network, credential, owner, policy, configuration, or deletion tool exists;
- handlers derive owner from server context and re-check resources;
- `propose_draft_patch` is non-mutating;
- tools and Agent remain independently default-off;
- provider capability, model, endpoint hash, and function-tool support fail closed;
- browser contracts contain no credential, internal host, storage path, raw provider response, or hidden reasoning;
- cancellation and recovery never automatically repeat an operation with an unknown side-effect outcome.

## Validation evidence

Automated tests cover strict registry schemas, owner isolation and field sanitization, read/proposal continuation, unknown tools, extra arguments, call/turn/approval budgets, argument/result size bounds, approve/reject immutability, concurrent duplicate approval, approval TTL, approval recovery, approval-task handoff, local and cross-Gateway cancellation, provider duplicate call replay, capability fail-closed behavior, and execution-lease takeover/fencing.

The loopback PostgreSQL suite covers migration roundtrips, lease claim/renew/expiry fencing, preservation of renewed leases across ordinary run updates, durable approvals across Gateway recreation, row-lock compare-and-swap, owner/Conversation constraints, and persisted Agent state. Tests use deterministic fake/injected providers and tools; they do not claim a real provider canary, real Authentik dual-user browser acceptance, a real gpu-server Runner, or production deployment.

## Rollback

1. Set `ONEIROI_GATEWAY_AGENT_TOOLS_ENABLED=false` to stop advertising or executing tools while retaining the text Agent.
2. Set `ONEIROI_GATEWAY_AGENT_ENABLED=false` to stop new Agent runs completely.
3. Allow active leased tasks to settle or cancel them through the owner-bound API.
4. Prefer a code-only rollback that leaves Agent tables and approval audit records intact.
5. If only the Stage D lease columns are intentionally disposable, downgrade to `0002_agent_runtime`; do this only after all Gateway versions that require leases are stopped.
6. Downgrading to `0001_dynamic_backend` drops all Agent tables and is destructive; never use it as an automatic production rollback.

No Cloudflare configuration, Pi/H100 service, gpu-server Runner, or production deployment is changed by Stage D.
