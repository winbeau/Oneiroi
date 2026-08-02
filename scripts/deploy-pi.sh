#!/usr/bin/env bash
# Deploy the complete Oneiroi Pi edge in LAN-only, no-login mode.

set -Eeuo pipefail
umask 077

DEPLOYMENT="${1-}"
[[ $# -eq 0 ]] || shift
LAN_HOST="${ONEIROI_LAN_HOST:-}"
PORT="${ONEIROI_WEB_PORT:-4173}"
BRANCH="${ONEIROI_GIT_BRANCH:-main}"
RELEASE_SHA="${ONEIROI_RELEASE_SHA:-}"
GATEWAY_URL="${ONEIROI_BFF_GATEWAY_BASE_URL:-}"
SKIP_PULL=0
SKIP_INSTALL=0

usage() {
    cat <<'EOF'
Usage:
  scripts/deploy-pi.sh lan --host ADDRESS [options]

Required:
  lan                    Deploy LAN-only mode; public video Tunnel is disabled first
  --host ADDRESS         Pi LAN address, for example 192.168.3.250

Options:
  --port PORT            Web port (default: 4173)
  --gateway-url URL      H100 BFF URL; otherwise preserve bff.env's current value
  --branch NAME          Git branch to fast-forward (default: main)
  --release-sha SHA      Require the deployed checkout to match this commit
  --skip-pull            Deploy the current clean checkout
  --skip-install         Skip frozen pnpm/uv dependency sync
  -h, --help             Show this help

Example:
  scripts/deploy-pi.sh lan --host 192.168.3.250 \
    --gateway-url http://10.30.176.95:18000
EOF
}

fail() {
    echo "[oneiroi-pi] ERROR: $*" >&2
    exit 1
}

if [[ "$DEPLOYMENT" == "-h" || "$DEPLOYMENT" == "--help" ]]; then
    usage
    exit 0
fi
[[ "$DEPLOYMENT" == "lan" ]] || { usage >&2; fail "the first argument must be: lan"; }

while (($#)); do
    case "$1" in
        --host)
            [[ -n "${2-}" ]] || fail "--host requires a value"
            LAN_HOST="$2"
            shift 2
            ;;
        --port)
            [[ -n "${2-}" ]] || fail "--port requires a value"
            PORT="$2"
            shift 2
            ;;
        --gateway-url)
            [[ -n "${2-}" ]] || fail "--gateway-url requires a value"
            GATEWAY_URL="$2"
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

[[ -n "$LAN_HOST" ]] || fail "--host is required"
[[ "$PORT" =~ ^[0-9]+$ ]] && ((PORT >= 1 && PORT <= 65535)) || fail "invalid port: $PORT"
[[ -z "$GATEWAY_URL" || "$GATEWAY_URL" =~ ^https?://[^[:space:]]+$ ]] \
    || fail "invalid --gateway-url: $GATEWAY_URL"
command -v python3 >/dev/null 2>&1 || fail "required command is missing: python3"
python3 - "$LAN_HOST" <<'PY' || fail "--host must be an RFC1918 IPv4 LAN address"
from ipaddress import ip_address, ip_network
import sys

try:
    address = ip_address(sys.argv[1])
except ValueError:
    raise SystemExit(1)
networks = (
    ip_network("10.0.0.0/8"),
    ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"),
)
if address.version != 4 or not any(address in network for network in networks):
    raise SystemExit(1)
PY

for command_name in curl git install ip node pnpm python3 systemctl uv; do
    command -v "$command_name" >/dev/null 2>&1 || fail "required command is missing: $command_name"
done
ip -o addr show | grep -Fq " $LAN_HOST/" || fail "$LAN_HOST is not assigned to this Pi"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
EXPECTED_REPO="$HOME/oneiroi-studio"
[[ "$REPO_DIR" == "$EXPECTED_REPO" ]] \
    || fail "Pi systemd units require the checkout at $EXPECTED_REPO (current: $REPO_DIR)"
cd "$REPO_DIR"

[[ -z "$(git status --porcelain)" ]] \
    || fail "the checkout is not clean; commit, stash, or remove local files before deployment"

CONFIG_DIR="$HOME/.config/oneiroi"
USER_UNIT_DIR="$HOME/.config/systemd/user"
BFF_ENV="$CONFIG_DIR/bff.env"
WEB_ENV="$CONFIG_DIR/web.env"
[[ -f "$BFF_ENV" ]] \
    || fail "$BFF_ENV is missing; install the Pi service assertion configuration first"

# Public access must be removed before development identity mode is enabled.
systemctl --user disable --now cloudflared-video.service >/dev/null 2>&1 || true
systemctl --user is-active --quiet cloudflared-video.service \
    && fail "cloudflared-video.service is still active" || true

if ((SKIP_PULL == 0)); then
    git fetch origin "$BRANCH"
    git checkout "$BRANCH"
    git pull --ff-only origin "$BRANCH"
fi
if [[ -n "$RELEASE_SHA" ]]; then
    [[ "$(git rev-parse HEAD)" == "$(git rev-parse "$RELEASE_SHA^{commit}")" ]] \
        || fail "checkout does not match required release SHA: $RELEASE_SHA"
fi
RELEASE_SHA="$(git rev-parse HEAD)"

if ((SKIP_INSTALL == 0)); then
    pnpm install --frozen-lockfile
    uv sync --all-packages --frozen
fi
pnpm --filter @oneiroi/web build
[[ -f apps/web/dist/index.html ]] || fail "web build did not produce apps/web/dist/index.html"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="$CONFIG_DIR/backups/$STAMP"
mkdir -p "$BACKUP_DIR" "$USER_UNIT_DIR"
for path in "$BFF_ENV" "$WEB_ENV" \
    "$USER_UNIT_DIR/oneiroi-bff.service" "$USER_UNIT_DIR/oneiroi-web.service"; do
    [[ -e "$path" ]] && cp -a "$path" "$BACKUP_DIR/"
done

upsert_env() {
    local file="$1"
    shift
    python3 - "$file" "$@" <<'PY'
import os
from pathlib import Path
import sys

path = Path(sys.argv[1])
updates = dict(item.split("=", 1) for item in sys.argv[2:])
lines = path.read_text().splitlines() if path.exists() else []
seen = set()
result = []
for line in lines:
    key = line.split("=", 1)[0] if "=" in line and not line.lstrip().startswith("#") else None
    if key in updates:
        result.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        result.append(line)
for key, value in updates.items():
    if key not in seen:
        result.append(f"{key}={value}")
temporary = path.with_suffix(path.suffix + ".tmp")
temporary.write_text("\n".join(result) + "\n")
os.chmod(temporary, 0o600)
os.replace(temporary, path)
PY
}

if [[ -z "$GATEWAY_URL" ]]; then
    GATEWAY_URL="$(python3 - "$BFF_ENV" <<'PY'
from pathlib import Path
import sys
for line in Path(sys.argv[1]).read_text().splitlines():
    if line.startswith("ONEIROI_BFF_GATEWAY_BASE_URL="):
        print(line.split("=", 1)[1])
        break
PY
)"
fi
[[ "$GATEWAY_URL" =~ ^https?://[^[:space:]]+$ ]] \
    || fail "bff.env has no valid gateway URL; pass --gateway-url"

ORIGIN="http://$LAN_HOST:$PORT"
upsert_env "$BFF_ENV" \
    "ONEIROI_BFF_ENVIRONMENT=development" \
    "ONEIROI_BFF_GATEWAY_BASE_URL=$GATEWAY_URL" \
    "ONEIROI_BFF_REQUEST_TIMEOUT_SECONDS=1800" \
    "ONEIROI_BFF_ALLOWED_ORIGINS=$ORIGIN" \
    "ONEIROI_BFF_REQUIRE_INBOUND_SERVICE_AUTH=false"
upsert_env "$WEB_ENV" \
    "ONEIROI_RELEASE_SHA=$RELEASE_SHA" \
    "ONEIROI_WEB_HOST=$LAN_HOST" \
    "ONEIROI_WEB_PORT=$PORT" \
    "ONEIROI_BFF_TARGET=http://127.0.0.1:8000" \
    "ONEIROI_MAX_REQUEST_BODY_BYTES=20971520"

install -m 0644 infra/systemd/user/oneiroi-bff.service "$USER_UNIT_DIR/oneiroi-bff.service"
install -m 0644 infra/systemd/user/oneiroi-web.service "$USER_UNIT_DIR/oneiroi-web.service"
systemctl --user daemon-reload
systemctl --user enable oneiroi-bff.service oneiroi-web.service >/dev/null
systemctl --user restart oneiroi-bff.service
systemctl --user restart oneiroi-web.service

wait_for_health() {
    local name="$1"
    local url="$2"
    for _ in {1..30}; do
        curl --noproxy '*' --fail --silent --show-error --max-time 2 "$url" >/dev/null 2>&1 && return 0
        sleep 1
    done
    journalctl --user -u "$name" -n 30 --no-pager >&2 || true
    fail "$name did not become healthy: $url"
}

wait_for_health oneiroi-bff.service http://127.0.0.1:8000/healthz
wait_for_health oneiroi-web.service "$ORIGIN/healthz"
systemctl --user is-active --quiet oneiroi-bff.service oneiroi-web.service \
    || fail "Pi services are not active"
systemctl --user is-active --quiet cloudflared-video.service \
    && fail "public video Tunnel unexpectedly became active" || true

printf '%s\n' \
    "[oneiroi-pi] LAN deployment complete" \
    "URL:        $ORIGIN" \
    "Release:    $RELEASE_SHA" \
    "Gateway:    $GATEWAY_URL" \
    "Tunnel:     disabled/inactive" \
    "Backup:     $BACKUP_DIR"
