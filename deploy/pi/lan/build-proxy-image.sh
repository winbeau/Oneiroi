#!/usr/bin/env bash
set -Eeuo pipefail
umask 022

IMAGE="${ONEIROI_LAN_PROXY_IMAGE:-local/oneiroi-lan-proxy:1}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT

for command_name in cp docker ldd python3 readlink tar; do
    command -v "$command_name" >/dev/null 2>&1 || {
        echo "ERROR: required command is missing: $command_name" >&2
        exit 1
    }
done

PYTHON_BIN="$(readlink -f "$(command -v python3)")"
PYTHON_STDLIB="$(python3 -c 'import sysconfig; print(sysconfig.get_paths()["stdlib"])')"
install -D -m 0755 "$PYTHON_BIN" "$BUILD_DIR/rootfs$PYTHON_BIN"
cp -a --parents "$PYTHON_STDLIB" "$BUILD_DIR/rootfs"
install -m 0755 "$SCRIPT_DIR/lan-proxy.py" "$BUILD_DIR/rootfs/lan-proxy.py"

{
    ldd "$PYTHON_BIN"
    find "$PYTHON_STDLIB" -type f -name '*.so' -exec ldd {} \; 2>/dev/null || true
} | awk '{ for (field = 1; field <= NF; field += 1) if ($field ~ /^\//) { print $field; break } }' |
    sort -u |
    while IFS= read -r library; do
        cp --parents -L "$library" "$BUILD_DIR/rootfs"
    done

tar -C "$BUILD_DIR/rootfs" -cf - . | docker import - "$IMAGE" >/dev/null
printf '%s %s\n' "$IMAGE" "$PYTHON_BIN"
