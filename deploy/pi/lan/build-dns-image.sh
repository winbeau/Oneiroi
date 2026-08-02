#!/usr/bin/env bash
set -Eeuo pipefail
umask 022

BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT

for command_name in cp dnsmasq docker ldd readlink tar; do
    command -v "$command_name" >/dev/null 2>&1 || {
        echo "ERROR: required command is missing: $command_name" >&2
        exit 1
    }
done

DNSMASQ_BIN="$(readlink -f "$(command -v dnsmasq)")"
DNSMASQ_VERSION="$(dnsmasq --version | awk 'NR == 1 { print $3 }')"
IMAGE="${ONEIROI_LAN_DNS_IMAGE:-local/oneiroi-dnsmasq:$DNSMASQ_VERSION}"
install -D -m 0755 "$DNSMASQ_BIN" "$BUILD_DIR/rootfs$DNSMASQ_BIN"

ldd "$DNSMASQ_BIN" |
    awk '{ for (index = 1; index <= NF; index += 1) if ($index ~ /^\//) { print $index; break } }' |
    sort -u |
    while IFS= read -r library; do
        cp --parents -L "$library" "$BUILD_DIR/rootfs"
    done

mkdir -p "$BUILD_DIR/rootfs/etc"
printf '%s\n' 'root:x:0:0:root:/root:/usr/sbin/nologin' >"$BUILD_DIR/rootfs/etc/passwd"
printf '%s\n' 'root:x:0:' >"$BUILD_DIR/rootfs/etc/group"
tar -C "$BUILD_DIR/rootfs" -cf - . | docker import - "$IMAGE" >/dev/null
printf '%s %s\n' "$IMAGE" "$DNSMASQ_BIN"
