#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tls_dir="${PATIENT_APP_TLS_DIR:-${TMPDIR:-/tmp}/patient-app-staging-tls}"
listen_port="${PATIENT_APP_TLS_PORT:-58443}"
umask 077
mkdir -p "$tls_dir"

if [[ ! -f "$tls_dir/ca.key" || ! -f "$tls_dir/ca.crt" ]]; then
  openssl genrsa -out "$tls_dir/ca.key" 3072 >/dev/null 2>&1
  openssl req -x509 -new -nodes -key "$tls_dir/ca.key" -sha256 -days 30 \
    -subj "/CN=Patient App local staging test CA" -out "$tls_dir/ca.crt" >/dev/null 2>&1
fi

if [[ ! -f "$tls_dir/server.key" || ! -f "$tls_dir/server.crt" ]]; then
  openssl genrsa -out "$tls_dir/server.key" 2048 >/dev/null 2>&1
  openssl req -new -key "$tls_dir/server.key" \
    -subj "/CN=localhost" -out "$tls_dir/server.csr" >/dev/null 2>&1
  cat > "$tls_dir/server.ext" <<'EOF'
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
subjectAltName=@alt_names
[alt_names]
DNS.1=localhost
IP.1=127.0.0.1
IP.2=::1
EOF
  openssl x509 -req -in "$tls_dir/server.csr" -CA "$tls_dir/ca.crt" -CAkey "$tls_dir/ca.key" \
    -CAcreateserial -out "$tls_dir/server.crt" -days 30 -sha256 -extfile "$tls_dir/server.ext" >/dev/null 2>&1
fi

if [[ -f "$tls_dir/pid" ]] && kill -0 "$(cat "$tls_dir/pid")" 2>/dev/null; then
  kill "$(cat "$tls_dir/pid")" 2>/dev/null || true
fi
nohup python3 "$script_dir/local_https_proxy.py" --listen-port "$listen_port" \
  --cert "$tls_dir/server.crt" --key "$tls_dir/server.key" \
  > "$tls_dir/server.log" 2>&1 &
echo $! > "$tls_dir/pid"
sleep 1
if ! kill -0 "$(cat "$tls_dir/pid")" 2>/dev/null; then
  cat "$tls_dir/server.log" >&2
  exit 1
fi
printf 'PATIENT_APP_STAGING_BASE_URL=https://127.0.0.1:%s\n' "$listen_port"
printf 'PATIENT_APP_STAGING_CA=%s\n' "$tls_dir/ca.crt"
