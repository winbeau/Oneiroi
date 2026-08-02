#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

LAN_HOST=""
HOSTNAME=""
UPSTREAM_PORT="4173"

fail() {
    echo "[oneiroi-lan-domain] ERROR: $*" >&2
    exit 1
}

while (($#)); do
    case "$1" in
        --host)
            LAN_HOST="${2-}"
            shift 2
            ;;
        --hostname)
            HOSTNAME="${2-}"
            shift 2
            ;;
        --upstream-port)
            UPSTREAM_PORT="${2-}"
            shift 2
            ;;
        *)
            fail "unknown argument: $1"
            ;;
    esac
done

[[ -n "$LAN_HOST" ]] || fail "--host is required"
[[ "$HOSTNAME" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] || fail "invalid --hostname"
[[ "$UPSTREAM_PORT" =~ ^[0-9]+$ ]] && ((UPSTREAM_PORT >= 1 && UPSTREAM_PORT <= 65535)) \
    || fail "invalid --upstream-port"
for command_name in curl dig docker ip openssl python3 readlink; do
    command -v "$command_name" >/dev/null 2>&1 || fail "required command is missing: $command_name"
done
ip -o addr show | grep -Fq " $LAN_HOST/" || fail "$LAN_HOST is not assigned to this Pi"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
read -r IMAGE PYTHON_BIN < <("$SCRIPT_DIR/build-proxy-image.sh")
read -r DNS_IMAGE DNSMASQ_BIN < <("$SCRIPT_DIR/build-dns-image.sh")

PKI_DIR="$HOME/.config/oneiroi/lan-pki"
mkdir -p "$PKI_DIR"
chmod 700 "$PKI_DIR"
CA_KEY="$PKI_DIR/ca.key"
CA_CERT="$PKI_DIR/ca.crt"
SERVER_KEY="$PKI_DIR/$HOSTNAME.key"
SERVER_CSR="$PKI_DIR/$HOSTNAME.csr"
SERVER_CERT="$PKI_DIR/$HOSTNAME.crt"
SERVER_EXT="$PKI_DIR/$HOSTNAME.ext"

if [[ ! -s "$CA_KEY" || ! -s "$CA_CERT" ]]; then
    openssl genrsa -out "$CA_KEY" 4096 >/dev/null 2>&1
    openssl req -x509 -new -sha256 -days 3650 \
        -key "$CA_KEY" -out "$CA_CERT" \
        -subj "/CN=ICTHub LAN Root CA/O=ICTHub LAN" >/dev/null 2>&1
fi
openssl genrsa -out "$SERVER_KEY" 2048 >/dev/null 2>&1
openssl req -new -sha256 -key "$SERVER_KEY" -out "$SERVER_CSR" \
    -subj "/CN=$HOSTNAME/O=ICTHub LAN" >/dev/null 2>&1
cat >"$SERVER_EXT" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:$HOSTNAME
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
EOF
openssl x509 -req -sha256 -days 365 \
    -in "$SERVER_CSR" -CA "$CA_CERT" -CAkey "$CA_KEY" \
    -CAserial "$PKI_DIR/ca.srl" -CAcreateserial \
    -out "$SERVER_CERT" -extfile "$SERVER_EXT" >/dev/null 2>&1
chmod 600 "$CA_KEY"
# Docker user-namespace remapping must be able to read only the serving leaf key.
chmod 644 "$CA_CERT" "$SERVER_CERT" "$SERVER_KEY"
rm -f "$SERVER_CSR" "$SERVER_EXT"

for container in video-in-proxy video-in-tls video-in-dns; do
    docker rm -f "$container" >/dev/null 2>&1 || true
done

docker run -d --name video-in-dns --restart unless-stopped --network host \
    --read-only --pids-limit 16 --memory 64m --ulimit nofile=512:512 \
    --cap-drop ALL --cap-add NET_BIND_SERVICE --cap-add SETUID --cap-add SETGID \
    --security-opt no-new-privileges \
    "$DNS_IMAGE" "$DNSMASQ_BIN" \
    --keep-in-foreground --log-facility=- --port=53 \
    --listen-address="$LAN_HOST" --bind-interfaces --no-hosts --no-resolv \
    --domain-needed --bogus-priv --server=223.5.5.5 --server=180.76.76.76 \
    --local="/$HOSTNAME/" --host-record="$HOSTNAME,$LAN_HOST" \
    --local-ttl=60 --user=root --group=root --pid-file= >/dev/null

docker run -d --name video-in-proxy --restart unless-stopped --network host \
    --read-only --pids-limit 16 --memory 128m --ulimit nofile=1024:1024 \
    --cap-drop ALL --cap-add NET_BIND_SERVICE --security-opt no-new-privileges \
    -e PYTHONDONTWRITEBYTECODE=1 \
    "$IMAGE" "$PYTHON_BIN" /lan-proxy.py \
    "$LAN_HOST" 80 "$LAN_HOST" "$UPSTREAM_PORT" >/dev/null

docker run -d --name video-in-tls --restart unless-stopped --network host \
    --read-only --pids-limit 16 --memory 128m --ulimit nofile=1024:1024 \
    --cap-drop ALL --cap-add NET_BIND_SERVICE --security-opt no-new-privileges \
    -e PYTHONDONTWRITEBYTECODE=1 \
    -v "$SERVER_CERT:/certs/server.crt:ro" \
    -v "$SERVER_KEY:/certs/server.key:ro" \
    "$IMAGE" "$PYTHON_BIN" /lan-proxy.py \
    "$LAN_HOST" 443 "$LAN_HOST" "$UPSTREAM_PORT" \
    --certificate /certs/server.crt --private-key /certs/server.key >/dev/null

for _ in {1..20}; do
    if [[ "$(dig +short "@$LAN_HOST" "$HOSTNAME" A | tail -1)" == "$LAN_HOST" ]] &&
        curl --noproxy '*' --fail --silent --show-error --max-time 2 \
            --resolve "$HOSTNAME:80:$LAN_HOST" "http://$HOSTNAME/healthz" >/dev/null 2>&1 &&
        curl --noproxy '*' --fail --silent --show-error --max-time 2 \
            --cacert "$CA_CERT" --resolve "$HOSTNAME:443:$LAN_HOST" \
            "https://$HOSTNAME/healthz" >/dev/null 2>&1; then
        printf '%s\n' \
            "[oneiroi-lan-domain] ready" \
            "HTTPS:   https://$HOSTNAME" \
            "DNS:     $HOSTNAME -> $LAN_HOST" \
            "CA cert: $CA_CERT"
        exit 0
    fi
    sleep 1
done

docker logs --tail 30 video-in-proxy >&2 || true
docker logs --tail 30 video-in-tls >&2 || true
fail "domain health validation failed"
