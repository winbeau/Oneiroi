#!/usr/bin/env bash
# Deploy the Oneiroi CPU edge (Pi5): update web origin and BFF in place.
#
# Runs on the CPU host itself. Pulls the latest release, syncs the immutable
# web origin (dist + release-SHA pin), restarts the systemd user units and
# verifies health. The release-SHA pin is updated automatically so the web
# origin never rejects the freshly pulled checkout.

set -Eeuo pipefail
umask 077

LAN_HOST="${ONEIROI_LAN_HOST:-192.168.3.250}"
PORT="${ONEIROI_WEB_PORT:-4173}"
BRANCH="${ONEIROI_GIT_BRANCH:-main}"
SKIP_PULL=0
SKIP_INSTALL=0

usage() {
    cat <<'EOF'
Usage:
  scripts/deploy-cpu.sh [options]

Deploy the Oneiroi CPU edge in place. Expected checkout: $HOME/oneiroi-studio.

Options:
  --host ADDRESS       Pi LAN address (default: 192.168.3.250)
  --port PORT          Web origin port (default: 4173)
  --branch NAME        Git branch to fast-forward (default: main)
  --skip-pull          Deploy the current clean checkout
  --skip-install       Skip frozen pnpm dependency sync
  -h, --help           Show this help

Example:
  scripts/deploy-cpu.sh
  scripts/deploy-cpu.sh --branch main --skip-pull
EOF
}

fail() {
    echo "[oneiroi-cpu] ERROR: $*" >&2
    exit 1
}

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

[[ "$PORT" =~ ^[0-9]+$ ]] && ((PORT >= 1 && PORT <= 65535)) || fail "invalid port: $PORT"
for command_name in curl git install ip node pnpm systemctl; do
    command -v "$command_name" >/dev/null 2>&1 || fail "required command is missing: $command_name"
done
ip -o addr show | grep -Fq " $LAN_HOST/" || fail "$LAN_HOST is not assigned to this host"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
EXPECTED_REPO="$HOME/oneiroi-studio"
[[ "$REPO_DIR" == "$EXPECTED_REPO" ]] \
    || fail "CPU systemd units require the checkout at $EXPECTED_REPO (current: $REPO_DIR)"
cd "$REPO_DIR"

[[ -z "$(git status --porcelain)" ]] \
    || fail "the checkout is not clean; commit, stash, or remove local files before deployment"

CONFIG_DIR="$HOME/.config/oneiroi"
BFF_ENV="$CONFIG_DIR/bff.env"
WEB_ENV="$CONFIG_DIR/web.env"
[[ -f "$BFF_ENV" ]] \
    || fail "$BFF_ENV is missing; configure the Pi service assertion settings first"

if ((SKIP_PULL == 0)); then
    git fetch origin "$BRANCH"
    git checkout "$BRANCH"
    git pull --ff-only origin "$BRANCH"
fi
RELEASE_SHA="$(git rev-parse HEAD)"

if ((SKIP_INSTALL == 0)); then
    pnpm install --frozen-lockfile
fi
pnpm --filter @oneiroi/web build
[[ -f apps/web/dist/index.html ]] || fail "web build did not produce apps/web/dist/index.html"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="$CONFIG_DIR/backups/$STAMP"
mkdir -p "$BACKUP_DIR"
for path in "$BFF_ENV" "$WEB_ENV" \
    "$HOME/.config/systemd/user/oneiroi-bff.service" \
    "$HOME/.config/systemd/user/oneiroi-web.service"; do
    [[ -e "$path" ]] && cp -a "$path" "$BACKUP_DIR/"
done

upsert_env() {
    local file="$1"
    shift
    python3 - "$file" "$@" <<'PY'
from pathlib import Path
import os
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

# Keep the release-SHA pin in sync with the checkout; otherwise the immutable
# origin refuses to start (classic "checkout does not match required release SHA").
upsert_env "$WEB_ENV" \
    "ONEIROI_RELEASE_SHA=$RELEASE_SHA" \
    "ONEIROI_WEB_HOST=$LAN_HOST" \
    "ONEIROI_WEB_PORT=$PORT"

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

ORIGIN="http://$LAN_HOST:$PORT"
wait_for_health oneiroi-bff.service http://127.0.0.1:8000/healthz
wait_for_health oneiroi-web.service "$ORIGIN/healthz"
systemctl --user is-active --quiet oneiroi-bff.service oneiroi-web.service \
    || fail "CPU services are not active"

printf '%s\n' \
    "[oneiroi-cpu] deployment complete" \
    "URL:        $ORIGIN" \
    "Release:    $RELEASE_SHA" \
    "BFF:        http://127.0.0.1:8000/healthz" \
    "Backup:     $BACKUP_DIR"
