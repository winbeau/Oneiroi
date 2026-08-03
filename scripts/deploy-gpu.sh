#!/usr/bin/env bash
# Deploy the Oneiroi GPU host (H100): update gateway and BFF in place.
#
# Runs on the GPU host itself. Pulls the latest release, syncs Python deps,
# restarts the supervisor-managed gateway/BFF and verifies health. Secrets in
# oneiroi-config/*-env.json are never touched or overwritten.

set -Eeuo pipefail
umask 077

CHECKOUT="${ONEIROI_GPU_CHECKOUT:-/root/wenbiao_zhao/Oneiroi}"
BRANCH="${ONEIROI_GIT_BRANCH:-main}"
CONFIG_DIR="${ONEIROI_GPU_CONFIG_DIR:-/root/wenbiao_zhao/oneiroi-config}"
SKIP_PULL=0
SKIP_INSTALL=0

usage() {
    cat <<'EOF'
Usage:
  scripts/deploy-gpu.sh [options]

Deploy the Oneiroi GPU host in place. Expected checkout:
  ${ONEIROI_GPU_CHECKOUT:-/root/wenbiao_zhao/Oneiroi}
with supervisor programs oneiroi-gateway and oneiroi-bff.

Options:
  --checkout PATH      Oneiroi checkout directory (default: /root/wenbiao_zhao/Oneiroi)
  --config-dir PATH    Runtime config directory (default: /root/wenbiao_zhao/oneiroi-config)
  --branch NAME        Git branch to fast-forward (default: main)
  --skip-pull          Deploy the current clean checkout
  --skip-install       Skip frozen uv dependency sync
  -h, --help           Show this help

Example:
  scripts/deploy-gpu.sh
  scripts/deploy-gpu.sh --checkout /root/wenbiao_zhao/Oneiroi
EOF
}

fail() {
    echo "[oneiroi-gpu] ERROR: $*" >&2
    exit 1
}

while (($#)); do
    case "$1" in
        --checkout)
            [[ -n "${2-}" ]] || fail "--checkout requires a value"
            CHECKOUT="$2"
            shift 2
            ;;
        --config-dir)
            [[ -n "${2-}" ]] || fail "--config-dir requires a value"
            CONFIG_DIR="$2"
            shift 2
            ;;
        --branch)
            [[ -n "${2-}" ]] || fail "--branch requires a value"
            BRANCH="$2"
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

[[ -d "$CHECKOUT/.git" ]] || fail "checkout is missing its git metadata: $CHECKOUT"
cd "$CHECKOUT"

for command_name in curl git supervisorctl uv; do
    command -v "$command_name" >/dev/null 2>&1 || fail "required command is missing: $command_name"
done

[[ -z "$(git status --porcelain)" ]] \
    || fail "the checkout is not clean; commit, stash, or remove local files before deployment"
for program in oneiroi-gateway oneiroi-bff; do
    supervisorctl status "$program" >/dev/null 2>&1 || fail "supervisor program is missing: $program"
done

if ((SKIP_PULL == 0)); then
    git fetch origin "$BRANCH"
    git checkout "$BRANCH"
    git pull --ff-only origin "$BRANCH"
fi
RELEASE_SHA="$(git rev-parse HEAD)"

if ((SKIP_INSTALL == 0)); then
    uv sync --all-packages --frozen
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="$CONFIG_DIR/backups/$STAMP"
mkdir -p "$BACKUP_DIR"
for file in gateway-env.json bff-env.json; do
    [[ -e "$CONFIG_DIR/$file" ]] && cp -a "$CONFIG_DIR/$file" "$BACKUP_DIR/"
done

supervisorctl restart oneiroi-gateway oneiroi-bff

wait_for_health() {
    local program="$1"
    local url="$2"
    for _ in {1..30}; do
        curl --noproxy '*' --fail --silent --show-error --max-time 2 "$url" >/dev/null 2>&1 && return 0
        sleep 1
    done
    tail -n 30 "$CONFIG_DIR/$program.log" >&2 || true
    fail "$program did not become healthy: $url"
}

wait_for_health oneiroi-gateway http://127.0.0.1:18010/healthz
wait_for_health oneiroi-bff http://127.0.0.1:18000/healthz
supervisorctl status oneiroi-gateway oneiroi-bff

printf '%s\n' \
    "[oneiroi-gpu] deployment complete" \
    "Checkout:   $CHECKOUT" \
    "Release:    $RELEASE_SHA" \
    "Gateway:    http://127.0.0.1:18010/healthz" \
    "BFF:        http://127.0.0.1:18000/healthz" \
    "Config:     $CONFIG_DIR (secrets preserved)" \
    "Backup:     $BACKUP_DIR"
