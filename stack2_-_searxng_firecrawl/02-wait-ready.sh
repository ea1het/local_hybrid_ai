#!/usr/bin/env bash
set -Eeuo pipefail

STACK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ENV_FILE="${STACK_DIR}/.env"
LOCK_FILE="${STACK_DIR}/.lock"
TIMEOUT_SECONDS="${STACK2_READY_TIMEOUT_SECONDS:-90}"

log() { printf '[stack2-ready] %s\n' "$*"; }
die() { printf '[stack2-ready] ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "run as root"
command -v docker >/dev/null 2>&1 || die "docker is not installed"
[[ -f "${ENV_FILE}" ]] || die "missing ${ENV_FILE}"
[[ -f "${LOCK_FILE}" ]] || die "Stack2 is not PREPARED"
[[ "${TIMEOUT_SECONDS}" =~ ^[0-9]+$ ]] || die "STACK2_READY_TIMEOUT_SECONDS must be an integer"

container_running() {
  local name="$1"
  [[ "$(docker inspect -f '{{.State.Running}}' "${name}" 2>/dev/null || true)" == "true" ]]
}

tcp_from_firecrawl() {
  local host="$1" port="$2"
  docker exec firecrawl-api node -e '
const net = require("net");
const host = process.argv[1];
const port = Number(process.argv[2]);
const socket = net.createConnection({host, port});
const finish = (ok) => { socket.destroy(); process.exit(ok ? 0 : 1); };
socket.setTimeout(1500);
socket.once("connect", () => finish(true));
socket.once("timeout", () => finish(false));
socket.once("error", () => finish(false));
' "${host}" "${port}" >/dev/null 2>&1
}

start="$(date +%s)"
while :; do
  if container_running searxng && \
     container_running firecrawl-api && \
     tcp_from_firecrawl searxng 8080 && \
     tcp_from_firecrawl firecrawl-api 3002; then
    log "web.search endpoint searxng:8080: READY"
    log "web.extract endpoint firecrawl-api:3002: READY"
    exit 0
  fi

  now="$(date +%s)"
  elapsed=$((now - start))
  if (( elapsed >= TIMEOUT_SECONDS )); then
    die "Stack2 capability endpoints did not become ready within ${TIMEOUT_SECONDS}s"
  fi
  sleep 1
done
