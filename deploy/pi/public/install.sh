#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

HOSTNAME="video-in.icthub.top"
RELEASE_SHA=""

fail() {
    echo "[oneiroi-public] ERROR: $*" >&2
    exit 1
}

while (($#)); do
    case "$1" in
        --hostname)
            HOSTNAME="${2-}"
            shift 2
            ;;
        --release-sha)
            RELEASE_SHA="${2-}"
            shift 2
            ;;
        *)
            fail "unknown argument: $1"
            ;;
    esac
done

[[ "$HOSTNAME" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] || fail "invalid --hostname"
for command_name in curl git install python3 systemctl; do
    command -v "$command_name" >/dev/null 2>&1 || fail "required command is missing: $command_name"
done

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_DIR"
[[ "$REPO_DIR" == "$HOME/oneiroi-studio" ]] || fail "expected checkout at $HOME/oneiroi-studio"
[[ -z "$(git status --porcelain)" ]] || fail "the checkout is not clean"
[[ -n "$RELEASE_SHA" ]] || RELEASE_SHA="$(git rev-parse HEAD)"
[[ "$(git rev-parse HEAD)" == "$(git rev-parse "$RELEASE_SHA^{commit}")" ]] \
    || fail "checkout does not match release SHA: $RELEASE_SHA"

CONFIG_DIR="$HOME/.config/oneiroi"
USER_UNIT_DIR="$HOME/.config/systemd/user"
SOURCE_ENV="$CONFIG_DIR/bff.env"
PUBLIC_BFF_ENV="$CONFIG_DIR/bff-public.env"
PUBLIC_WEB_ENV="$CONFIG_DIR/web-public.env"
CLOUDFLARED_CONFIG="$HOME/.cloudflared/video.yml"
CLOUDFLARED_BIN="$HOME/.local/bin/cloudflared"
[[ -f "$SOURCE_ENV" ]] || fail "$SOURCE_ENV is missing"
[[ -x "$CLOUDFLARED_BIN" ]] || fail "$CLOUDFLARED_BIN is missing"
[[ -f "$CLOUDFLARED_CONFIG" ]] || fail "$CLOUDFLARED_CONFIG is missing"

python3 - "$SOURCE_ENV" <<'PY' || fail "public Access JWT configuration is incomplete"
from pathlib import Path
import sys

required = {
    "ONEIROI_BFF_ACCESS_ISSUER",
    "ONEIROI_BFF_ACCESS_AUDIENCE",
    "ONEIROI_BFF_ACCESS_JWKS_URL",
    "ONEIROI_BFF_SERVICE_PRIVATE_KEY_FILE",
}
values = {}
for line in Path(sys.argv[1]).read_text().splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        key, value = line.split("=", 1)
        values[key] = value.strip()
if any(not values.get(key) for key in required):
    raise SystemExit(1)
PY

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

cp "$SOURCE_ENV" "$PUBLIC_BFF_ENV"
chmod 600 "$PUBLIC_BFF_ENV"
upsert_env "$PUBLIC_BFF_ENV" \
    "ONEIROI_BFF_ENVIRONMENT=production" \
    "ONEIROI_BFF_ALLOWED_ORIGINS=https://$HOSTNAME" \
    "ONEIROI_BFF_REQUIRE_INBOUND_SERVICE_AUTH=false"
upsert_env "$PUBLIC_WEB_ENV" \
    "ONEIROI_RELEASE_SHA=$RELEASE_SHA" \
    "ONEIROI_WEB_HOST=127.0.0.1" \
    "ONEIROI_WEB_PORT=4174" \
    "ONEIROI_BFF_TARGET=http://127.0.0.1:8001" \
    "ONEIROI_MAX_REQUEST_BODY_BYTES=20971520"

TUNNEL_ID="$(awk -F': *' '$1 == "tunnel" {print $2; exit}' "$CLOUDFLARED_CONFIG")"
CREDENTIALS_FILE="$(awk -F': *' '$1 == "credentials-file" {print $2; exit}' "$CLOUDFLARED_CONFIG")"
[[ -n "$TUNNEL_ID" ]] || fail "video.yml has no tunnel id"
[[ -n "$CREDENTIALS_FILE" && -f "$CREDENTIALS_FILE" ]] || fail "video.yml credentials file is missing"
cat >"$CLOUDFLARED_CONFIG.tmp" <<EOF
tunnel: $TUNNEL_ID
credentials-file: $CREDENTIALS_FILE
protocol: http2

ingress:
  - hostname: $HOSTNAME
    service: http://127.0.0.1:4174
    originRequest:
      connectTimeout: 10s
      httpHostHeader: 127.0.0.1
  - service: http_status:404
EOF
chmod 600 "$CLOUDFLARED_CONFIG.tmp"
mv "$CLOUDFLARED_CONFIG.tmp" "$CLOUDFLARED_CONFIG"

mkdir -p "$USER_UNIT_DIR"
install -m 0644 infra/systemd/user/oneiroi-bff-public.service "$USER_UNIT_DIR/oneiroi-bff-public.service"
install -m 0644 infra/systemd/user/oneiroi-web-public.service "$USER_UNIT_DIR/oneiroi-web-public.service"
install -m 0644 infra/systemd/user/cloudflared-video.service "$USER_UNIT_DIR/cloudflared-video.service"
rm -rf "$USER_UNIT_DIR/cloudflared-video.service.d"
systemctl --user daemon-reload
systemctl --user enable oneiroi-bff-public.service oneiroi-web-public.service cloudflared-video.service >/dev/null
systemctl --user restart oneiroi-bff-public.service
systemctl --user restart oneiroi-web-public.service

wait_for_health() {
    local unit="$1"
    local url="$2"
    for _ in {1..30}; do
        curl --noproxy '*' --fail --silent --show-error --max-time 2 "$url" >/dev/null 2>&1 && return 0
        sleep 1
    done
    journalctl --user -u "$unit" -n 30 --no-pager >&2 || true
    fail "$unit did not become healthy"
}
wait_for_health oneiroi-bff-public.service http://127.0.0.1:8001/healthz
wait_for_health oneiroi-web-public.service http://127.0.0.1:4174/healthz

STATUS="$(curl --noproxy '*' --silent --output /dev/null --write-out '%{http_code}' --max-time 5 \
    -H 'Origin: https://video-in.invalid' http://127.0.0.1:8001/v1/jobs || true)"
[[ "$STATUS" == "401" || "$STATUS" == "403" ]] || fail "public BFF accepted a request without Access JWT: HTTP $STATUS"

HTTP_PROXY=http://127.0.0.1:10808 HTTPS_PROXY=http://127.0.0.1:10808 \
    "$CLOUDFLARED_BIN" tunnel route dns --overwrite-dns "$TUNNEL_ID" "$HOSTNAME" >/dev/null
systemctl --user restart cloudflared-video.service
systemctl --user is-active --quiet oneiroi-bff-public.service oneiroi-web-public.service cloudflared-video.service \
    || fail "one or more public services are inactive"

printf '%s\n' \
    "[oneiroi-public] ready" \
    "URL:      https://$HOSTNAME" \
    "BFF:      production Access JWT verification" \
    "Release:  $RELEASE_SHA"
