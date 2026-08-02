# GPT Agent implementation status

Last updated: 2026-08-02

Branch: `gpt-agent`
Starting commit: `297c7e1c4321ae720d3631e3a0a89bd7826a39dc`

This file records implementation state, test evidence, external blockers, stage commits, and rollback points. A stage is not marked complete when it still requires a real account, external credential, provider capability, gpu-server Runner, or production authorization.

## Baseline before Agent changes

The independent worktree started clean on `gpt-agent` at the required starting commit. The first test attempt established that this new worktree had no installed workspace dependencies; those failures were environment setup failures (`ModuleNotFoundError`, missing `eslint`), not repository regressions. After `uv sync --all-packages --frozen` and `pnpm install --frozen-lockfile`:

| Check | Baseline result |
|---|---|
| `uv run ruff check .` | passed |
| `uv run pytest` | 69 passed, 5 skipped; existing Starlette 422 deprecation warning; one existing compute lease renewal task warning was observed in the first full run |
| `pnpm check` | passed |
| `pnpm check:api` | passed |
| `pnpm --filter @oneiroi/web e2e` | 13 passed, 1 skipped |
| `git diff --check` | passed |
| tracked credential scan | passed |
| `/gpt-tmp/` ignore guard | confirmed by `.gitignore` |

## Stage status

| Stage | State | Implementation commit | External blocker |
|---|---|---|---|
| A. Provider and configuration | implemented; real canary blocked | `340118be27cd3c4ec71b4bf73dae9fef994ed226` | rotated credential has not been injected into restricted Gateway runtime; real image model/return mode, rate-limit format, and WebSocket support are therefore not claimed |
| B. Minimal Agent API and prompt assistant | implemented | `f6840c4d816b0fa688f8056482f593dc3bccfc62` | real provider canary remains blocked; deterministic fake-provider implementation is complete |
| C. Durable Agent runtime | implemented | `f6840c4d816b0fa688f8056482f593dc3bccfc62` | production migration requires later release authorization; local PostgreSQL migration and persistence checks pass |
| D. Controlled tools and approval | implemented locally; final quality gate pending | — | no local fake-provider blocker; real costly image/Job tools belong to later stages |
| E. Image generation and assetization | pending | — | real provider image capability remains blocked; fake/base64/file-ID/URL paths can proceed |
| F. Frontend Agent experience and Job orchestration | pending | — | real video E2E requires a gpu-server Runner; fake Job orchestration can proceed |
| G. Security, operations, and rollout | pending | — | real Authentik dual-user and production canary require user/operator authorization |

## Stage A evidence

Implemented:

- disabled-by-default Gateway Agent settings;
- validated HTTPS/credential-free base URL, required key/model when enabled, `SecretStr`, and immutable `store=false`;
- explicit SSE transport with separately gated WebSocket canary declaration;
- `AgentProvider` protocol and deterministic fake provider;
- OpenAI-compatible `/responses` HTTP SSE adapter;
- normalized text, bounded reasoning summary, fragmented function arguments, image, usage, failure, and terminal events;
- duplicate source event de-duplication using SSE ID, provider event ID, or Responses `sequence_number`;
- strict recursive JSON Schema for tools and one-time finalized argument validation;
- total request deadline covering connection, response headers, streaming, retries, and cancellation cleanup;
- bounded retry/error mapping for auth, 429, context, timeout, 5xx, and interrupted streams;
- automatic image retry disabled;
- capability probe CLI with text, streaming, tool continuation, image input, optional image generation, optional error-format probe, usage, and WebSocket declaration-versus-verification record;
- endpoint/model-bound `0600` capability record with atomic write and fail-closed loading;
- safe `GET /v1/agent/capabilities` Gateway endpoint;
- OpenAPI and generated TypeScript DTO update;
- configuration, probe, security, and rollback documentation in `docs/agent-provider.md`.

Quality evidence after Stage A:

| Check | Result |
|---|---|
| `uv run ruff check .` | passed |
| `uv run pytest` | 109 passed, 5 skipped, 1 existing Starlette deprecation warning |
| targeted Agent tests | 40 passed before final fixture normalization; subsequent provider/SSE check 19 passed |
| `pnpm check` | passed |
| `pnpm check:api` | passed after commit |
| `pnpm --filter @oneiroi/web e2e` | 13 passed, 1 skipped |
| `git diff --check` and cached diff check | passed |
| staged credential-pattern scan | passed |
| real provider network calls in pytest | 0 |

## Stages B/C evidence

Implemented:

- canonical Agent thread, message, run, event, tool-call, approval, usage, status, and editable draft-proposal contracts;
- owner-bound minimal Agent API for idempotent run creation, run snapshot, cancellation, thread lookup, bounded messages, and durable SSE replay;
- a versioned system prompt that requests user-visible conclusions and proposals without exposing chain-of-thought;
- structured draft proposal validation; provider output never mutates the browser draft or starts a long-running Job without later explicit user action;
- `0002_agent_runtime` PostgreSQL migration and matching SQLAlchemy models;
- in-memory and SQL Agent repository implementations behind the same protocol;
- PostgreSQL-level partial unique active-run index, plus runtime enforcement, limiting each owner to one non-terminal run;
- row-lock and expected-state compare-and-swap for transitions, streamed event append, and completion so stale workers cannot overwrite cancellation or terminal state;
- composite database constraints binding owner, Conversation, thread, run, message, event, tool call, and approval relationships;
- durable event IDs, bounded 200-event replay pages, `Last-Event-ID`, terminal replay completion, and heartbeats;
- cancellation semantics that win over concurrent final delta, proposal, or completion writes;
- deterministic restart recovery: `cancelling` becomes `cancelled`; all other incomplete states, including pre-Stage-D `waiting_approval`, fail with `AGENT_RECOVERY_REQUIRED` and release the owner slot;
- bounded provider source events through `ONEIROI_GATEWAY_AGENT_MAX_EVENTS_PER_RUN=1000`, bounded text, bounded message queries, and owner-checked input Asset metadata;
- explicit Pi BFF route allowlist and reduced Agent JSON body limit; no wildcard Agent proxy;
- OpenAPI and generated TypeScript DTO updates;
- runtime, persistence, SSE, recovery, safety, validation, and rollback documentation in `docs/agent-runtime.md`.

Quality evidence for Stages B/C implementation commit `f6840c4d816b0fa688f8056482f593dc3bccfc62`:

| Check | Result |
|---|---|
| `uv run ruff check .` | passed |
| targeted Agent repository/runtime/settings tests | 23 passed |
| `uv run pytest` | 126 passed, 8 skipped, 1 existing Starlette deprecation warning |
| PostgreSQL migration `downgrade 0001_dynamic_backend` then `upgrade head` | passed |
| loopback PostgreSQL integration, including automated migration roundtrip | 5 passed |
| `pnpm check` | passed |
| `pnpm check:api` | passed after the stage commit established the generated OpenAPI/TypeScript baseline |
| Playwright | 13 passed, 1 skipped |
| `git diff --check` and high-entropy credential scan | passed |

## Stage D evidence

Implemented locally:

- strict server-owned `ToolRegistry` with version, description, recursive strict schema, risk, per-run limit, timeout, bounded result, and handler;
- owner-safe built-ins: `get_creation_context`, `list_assets`, `get_asset_metadata`, `get_job_snapshot`, and non-mutating `propose_draft_patch`;
- independently default-off tool capability gated by both `ONEIROI_GATEWAY_AGENT_TOOLS_ENABLED` and endpoint/model probe support for function tools;
- multi-turn provider continuation with bounded turns, tool calls, approvals, run time, canonical arguments, provider argument buffers, and tool results;
- durable tool-call and approval state, immutable canonical argument SHA-256, TTL expiration, approve/reject APIs, one-time claim, concurrent duplicate-decision idempotency, and provider call-ID replay checks;
- approval-task handoff when approval races the original provider task, with identity-safe task cleanup;
- local and cross-Gateway cancellation semantics that do not claim rollback of an already-running side effect and preserve tool-before-run terminal event ordering;
- `0003_agent_execution_lease` with executor ID, lease expiry, bounded renewal, expired-lease rejection, startup recovery filtering, and transactional fencing on every worker run/tool mutation;
- fail-closed recovery for `approved` or `running` unknown outcomes without replay, while valid pending approvals survive restart and restore their TTL tasks;
- prompt-injection hardening and explicit prohibition of shell, Python, SQL, filesystem, arbitrary HTTP/internal-network, credential, owner/path/configuration, and deletion tools;
- explicit Gateway and Pi BFF approve/reject route allowlists and bounded decision bodies;
- deterministic tests for registry validation, owner sanitization, continuation, budgets, TTL, duplicate approval, restart, handoff, cross-process cancel, stale executor takeover, renewed-lease preservation, and PostgreSQL row-lock persistence.

Final local validation after the lease-fencing fixes:

| Check | Result |
|---|---|
| `uv run ruff check .` | passed |
| focused Stage D Agent/runtime/repository tests | passed |
| `uv run pytest` | 148 passed, 9 skipped, 1 existing Starlette deprecation warning |
| loopback PostgreSQL integration, including `0001 -> head` migration roundtrip | 6 passed |
| `pnpm check` | passed |
| `pnpm check:api` | passed after staging regenerated OpenAPI/TypeScript artifacts |
| Playwright | 13 passed, 1 skipped |
| `git diff --check` and cached diff check | passed |
| final read-only P0/P1 review | no P0/P1 |

Scope notes:

- production built-ins in Stage D are read/proposal only; the write/costly/destructive approval engine is exercised with deterministic injected tools;
- no image generation, Asset creation, video Job creation/retry/cancel, arbitrary network access, or production side effect is enabled by this stage;
- real provider tools remain externally blocked until a restricted capability probe reports `functionTools=supported`;
- no Authentik, Cloudflare, Pi/H100 production service, or gpu-server Runner was changed.

Stages B/C security and scope notes:

- tests use the deterministic fake provider and make no real provider network call;
- no provider key, base URL override, raw provider event, storage path, or chain-of-thought enters browser contracts;
- no write/costly tool executes in Stages B/C; Stage D approval tables are schema-only reservations;
- no Authentik, Cloudflare, Pi/H100 production service, or gpu-server Runner was changed;
- Pi/H100 production remains frozen at `fa7c28cc98edf423e2be8762ad13b55f606389eb`.

Rollback:

1. Set `ONEIROI_GATEWAY_AGENT_ENABLED=false`; new runs fail closed while existing non-Agent APIs remain available.
2. Prefer a code-only rollback that leaves Agent tables intact.
3. If Agent data is intentionally disposable, `alembic downgrade 0001_dynamic_backend` drops all Agent tables; this destructive step is not an automatic production rollback.

Provider capability result:

- fixture/fake: text, SSE, reasoning summary, function tools, continuation, usage, image base64, file ID, URL, errors, interruption, duplicate IDs, cancellation, and timeouts pass;
- real `https://api.selab.top/v1` canary: **blocked, not run**;
- real image input/generation: **unknown until restricted probe**;
- independent image model: **unknown until restricted probe**;
- WebSocket: provider configuration declares support, but actual capability is **not verified** and remains unavailable;
- no credential from `gpt-tmp/auth.json` was read, printed, copied, logged, or committed.

Database impact: none. Stage A adds no migration or Agent state tables.

Rollback:

1. Set `ONEIROI_GATEWAY_AGENT_ENABLED=false`.
2. Keep image and WebSocket flags false.
3. Remove the capability-file setting if desired; do not delete unrelated data.
4. Revert commit `340118be27cd3c4ec71b4bf73dae9fef994ed226` if code rollback is required.

Production impact: none. Pi/H100 production remains frozen at `fa7c28cc98edf423e2be8762ad13b55f606389eb`; no deployment, restart, Cloudflare change, or runtime modification was performed.
