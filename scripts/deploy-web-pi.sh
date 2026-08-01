#!/usr/bin/env bash
# Build and serve the Oneiroi web release on the Raspberry Pi.

set -Eeuo pipefail
umask 022

MODE="${ONEIROI_WEB_MODE:-static}"
BRANCH="${ONEIROI_GIT_BRANCH:-main}"
HOST="${ONEIROI_WEB_HOST:-127.0.0.1}"
PORT="${ONEIROI_WEB_PORT:-4173}"
RELEASE_SHA="${ONEIROI_RELEASE_SHA:-}"
SKIP_PULL=0
SKIP_INSTALL=0
SKIP_BUILD=0

usage() {
    cat <<'EOF'
Usage:
  scripts/deploy-web-pi.sh [options]

Options:
  --mode static|preview|dev
                         static serves the immutable dist through the built-in origin
  --branch NAME         Git branch to fast-forward from origin (default: main)
  --release-sha SHA     Require the checkout to be exactly this commit
  --host ADDRESS        Listen address (default: 127.0.0.1)
  --port PORT           Listen port (default: 4173)
  --skip-pull           Do not run git pull --ff-only
  --skip-install        Do not run pnpm install --frozen-lockfile
  --skip-build          Do not rebuild an already staged dist directory
  -h, --help            Show this help

Environment equivalents:
  ONEIROI_WEB_MODE, ONEIROI_GIT_BRANCH, ONEIROI_RELEASE_SHA,
  ONEIROI_WEB_HOST, ONEIROI_WEB_PORT, ONEIROI_BFF_TARGET
EOF
}

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

while (($#)); do
    case "$1" in
        --mode)
            [[ -n "${2-}" ]] || fail "--mode requires a value"
            MODE="$2"
            shift 2
            ;;
        --branch)
            [[ -n "${2-}" ]] || fail "--branch requires a value"
            BRANCH="$2"
            shift 2
            ;;
        --release-sha)
            [[ -n "${2-}" ]] || fail "--release-sha requires a value"
            RELEASE_SHA="$2"
            shift 2
            ;;
        --host)
            [[ -n "${2-}" ]] || fail "--host requires a value"
            HOST="$2"
            shift 2
            ;;
        --port)
            [[ -n "${2-}" ]] || fail "--port requires a value"
            PORT="$2"
            shift 2
            ;;
        --skip-pull)
            SKIP_PULL=1
            shift
            ;;
        --skip-install)
            SKIP_INSTALL=1
            shift
            ;;
        --skip-build)
            SKIP_BUILD=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "unknown argument: $1"
            ;;
    esac
done

[[ "$MODE" == "static" || "$MODE" == "preview" || "$MODE" == "dev" ]] \
    || fail "--mode must be static, preview, or dev"
[[ "$PORT" =~ ^[0-9]+$ ]] && ((PORT >= 1 && PORT <= 65535)) || fail "invalid port: $PORT"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

for command_name in git node pnpm; do
    command -v "$command_name" >/dev/null 2>&1 || fail "required command is missing: $command_name"
done

[[ -z "$(git status --porcelain --untracked-files=no)" ]] \
    || fail "tracked files are modified; commit, stash, or reset before deployment"

if ((SKIP_PULL == 0)); then
    git fetch origin "$BRANCH"
    git checkout "$BRANCH"
    git pull --ff-only origin "$BRANCH"
fi

if [[ -n "$RELEASE_SHA" ]]; then
    [[ "$(git rev-parse HEAD)" == "$(git rev-parse "$RELEASE_SHA^{commit}")" ]] \
        || fail "checkout does not match required release SHA: $RELEASE_SHA"
fi

if ((SKIP_INSTALL == 0)); then
    pnpm install --frozen-lockfile
fi

printf '%s\n' \
    "Repository: $REPO_DIR" \
    "Commit:     $(git rev-parse HEAD)" \
    "Mode:       $MODE" \
    "Listen:     http://$HOST:$PORT"

if [[ "$MODE" == "static" ]]; then
    if ((SKIP_BUILD == 0)); then
        pnpm --filter @oneiroi/web build
    fi
    [[ -f apps/web/dist/index.html ]] || fail "static dist is missing; run without --skip-build first"
    exec env ONEIROI_WEB_HOST="$HOST" ONEIROI_WEB_PORT="$PORT" \
        node scripts/serve-web.mjs
fi

if [[ "$MODE" == "preview" ]]; then
    pnpm --filter @oneiroi/web build
    exec pnpm --filter @oneiroi/web exec vite preview --host "$HOST" --port "$PORT"
fi

exec pnpm --filter @oneiroi/web exec vite --host "$HOST" --port "$PORT"
