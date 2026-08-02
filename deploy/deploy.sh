#!/usr/bin/env bash
# Pi5 deployment entrypoint.
#   bash deploy/deploy.sh --internal  -> LAN-only, public services disabled
#   bash deploy/deploy.sh             -> LAN + public, with isolated BFF identity modes

set -Eeuo pipefail
umask 077

MODE="all"
LAN_HOST="${ONEIROI_LAN_HOST:-192.168.3.250}"
LAN_HOSTNAME="${ONEIROI_LAN_HOSTNAME:-video-in.icthub.top}"
GATEWAY_URL="${ONEIROI_BFF_GATEWAY_BASE_URL:-}"

usage() {
    cat <<'EOF'
Usage:
  bash deploy/deploy.sh --internal   Deploy only https://video-in.icthub.top on LAN
  bash deploy/deploy.sh              Deploy LAN and public endpoints

Environment overrides:
  ONEIROI_LAN_HOST
  ONEIROI_LAN_HOSTNAME
  ONEIROI_BFF_GATEWAY_BASE_URL
EOF
}

while (($#)); do
    case "$1" in
        --internal)
            MODE="internal"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: unknown argument: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

internal_args=(
    lan
    --host "$LAN_HOST"
    --hostname "$LAN_HOSTNAME"
)
[[ -n "$GATEWAY_URL" ]] && internal_args+=(--gateway-url "$GATEWAY_URL")
"$REPO_DIR/scripts/deploy-pi.sh" "${internal_args[@]}"

if [[ "$MODE" == "internal" ]]; then
    printf '%s\n' \
        "[oneiroi-deploy] internal-only deployment complete" \
        "URL: https://$LAN_HOSTNAME" \
        "Public services: disabled/inactive"
    exit 0
fi

RELEASE_SHA="$(git rev-parse HEAD)"
"$REPO_DIR/deploy/pi/public/install.sh" \
    --hostname "$LAN_HOSTNAME" \
    --release-sha "$RELEASE_SHA"

printf '%s\n' \
    "[oneiroi-deploy] internal + public deployment complete" \
    "URL: https://$LAN_HOSTNAME" \
    "Internal identity: development/no-login" \
    "Public identity: Cloudflare Access JWT required"
