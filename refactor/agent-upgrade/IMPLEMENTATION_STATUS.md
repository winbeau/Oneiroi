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
| B. Minimal Agent API and prompt assistant | pending | — | none for fake-provider implementation |
| C. Durable Agent runtime | pending | — | PostgreSQL integration requires the repository test database when migration tests run |
| D. Controlled tools and approval | pending | — | none for fake service tests |
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
