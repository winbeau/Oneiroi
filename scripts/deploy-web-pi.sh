#!/usr/bin/env bash
# Update Oneiroi from Git and expose the React/Vite frontend on the Raspberry Pi LAN.

set -Eeuo pipefail
umask 022

MODE="${ONEIROI_WEB_MODE:-preview}"
BRANCH="${ONEIROI_GIT_BRANCH:-main}"
HOST="${ONEIROI_WEB_HOST:-0.0.0.0}"
PORT="${ONEIROI_WEB_PORT:-}"
SKIP_PULL=0
SKIP_INSTALL=0

usage() {
    cat <<'EOF'
Usage:
  scripts/deploy-web-pi.sh [options]

Options:
  --mode preview|dev   preview builds first and serves dist; dev starts Vite HMR
  --branch NAME        Git branch to fast-forward from origin (default: main)
  --host ADDRESS       Listen address (default: 0.0.0.0)
  --port PORT          Listen port (preview default: 4173; dev default: 5173)
  --skip-pull          Do not run git pull --ff-only
  --skip-install       Do not run pnpm install --frozen-lockfile
  -h, --help           Show this help

Environment equivalents:
  ONEIROI_WEB_MODE, ONEIROI_GIT_BRANCH, ONEIROI_WEB_HOST, ONEIROI_WEB_PORT
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
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "unknown argument: $1"
            ;;
    esac
done

[[ "$MODE" == "preview" || "$MODE" == "dev" ]] || fail "--mode must be preview or dev"
PORT="${PORT:-$([[ "$MODE" == "preview" ]] && echo 4173 || echo 5173)}"
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

if ((SKIP_INSTALL == 0)); then
    pnpm install --frozen-lockfile
fi

printf '%s\n' \
    "Repository: $REPO_DIR" \
    "Commit:     $(git rev-parse --short HEAD)" \
    "Mode:       $MODE" \
    "Listen:     http://$HOST:$PORT"

if [[ "$MODE" == "preview" ]]; then
    pnpm --filter @oneiroi/web build
    exec pnpm --filter @oneiroi/web exec vite preview --host "$HOST" --port "$PORT"
fi

exec pnpm --filter @oneiroi/web exec vite --host "$HOST" --port "$PORT"
