#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

# Reconcile optional Stack6 capabilities without changing PREPARED state.
#
# Current capability:
#   web.search + web.extract
#     provider: local SearXNG + Firecrawl on NETWORK_NAME
#     absent/incomplete provider => Hermes web toolset remains disabled
#
# This script never creates provider resources and never changes .env/.lock.

STACK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ENV_FILE="${STACK_DIR}/.env"
LOCK_FILE="${STACK_DIR}/.lock"
SOURCE_CONFIG="${STACK_DIR}/config/hermes/config.yaml"
RESTART=false

log()  { printf '[capabilities] %s\n' "$*"; }
warn() { printf '[capabilities] WARNING: %s\n' "$*" >&2; }
die()  { printf '[capabilities] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage: 06-reconcile-capabilities.sh [--restart]

  --restart  recreate only the Hermes service when managed config changes and
             Hermes is already running. No other Stack6 service is restarted.
EOF
}

while (($#)); do
  case "$1" in
    --restart) RESTART=true ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
  shift
done

[[ "$(id -u)" -eq 0 ]] || die "run as root"
for cmd in docker awk grep install cmp mktemp sha256sum; do
  command -v "${cmd}" >/dev/null 2>&1 || die "missing required command: ${cmd}"
done

docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required"
[[ -f "${ENV_FILE}" ]] || die "missing ${ENV_FILE}"
[[ -f "${LOCK_FILE}" ]] || die "Stack6 is not PREPARED; run 01-prepare.sh first"
[[ -s "${SOURCE_CONFIG}" ]] || die "missing managed source ${SOURCE_CONFIG}"

ENV_SHA256_BEFORE="$(sha256sum "${ENV_FILE}" | awk '{print $1}')"
LOCK_SHA256_BEFORE="$(sha256sum "${LOCK_FILE}" | awk '{print $1}')"

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

required=(BASE_PATH NETWORK_NAME HERMES_SERVICE HERMES_CONTAINER HERMES_UID HERMES_GID HERMES_MODEL)
for key in "${required[@]}"; do
  [[ -n "${!key:-}" ]] || die "missing ${key} in .env"
done

[[ "${BASE_PATH}" == /* ]] || die "BASE_PATH must be absolute"
DEPLOYED_CONFIG="${BASE_PATH%/}/${HERMES_SERVICE}/config/config.yaml"
[[ -f "${DEPLOYED_CONFIG}" && ! -L "${DEPLOYED_CONFIG}" ]] || die "invalid deployed config: ${DEPLOYED_CONFIG}"

# Provider detection is deliberately all-or-nothing. A partial web provider is
# treated as unavailable so Hermes cannot silently use another backend.
container_ready_on_network() {
  local container="$1" running attached
  docker inspect "${container}" >/dev/null 2>&1 || return 1
  running="$(docker inspect -f '{{.State.Running}}' "${container}")"
  [[ "${running}" == "true" ]] || return 1
  attached="$(docker inspect -f "{{if index .NetworkSettings.Networks \"${NETWORK_NAME}\"}}yes{{else}}no{{end}}" "${container}")"
  [[ "${attached}" == "yes" ]]
}

WEB_ENABLED=false
if container_ready_on_network searxng && container_ready_on_network firecrawl-api; then
  [[ -n "${SEARXNG_URL:-}" ]] || die "web provider is present but SEARXNG_URL is empty"
  [[ -n "${FIRECRAWL_API_URL:-}" ]] || die "web provider is present but FIRECRAWL_API_URL is empty"
  WEB_ENABLED=true
  log "web.search + web.extract: available"
else
  log "web.search + web.extract: unavailable; Hermes web remains disabled"
fi

RENDERED="$(mktemp)"
trap 'rm -f "${RENDERED:-}"' EXIT

awk -v model="${HERMES_MODEL}" -v web_enabled="${WEB_ENABLED}" '
  {
    gsub(/\$\{HERMES_MODEL\}/, model)
    if ($0 ~ /^[[:space:]]*disabled_toolsets:[[:space:]]*\[web\][[:space:]]*$/ && web_enabled == "true") {
      sub(/\[web\]/, "[]")
    }
    print
  }
' "${SOURCE_CONFIG}" > "${RENDERED}"

[[ -s "${RENDERED}" ]] || die "rendered config is empty"
grep -qF '${HERMES_MODEL}' "${RENDERED}" && die "rendered config still contains HERMES_MODEL placeholder"

if "${WEB_ENABLED}"; then
  grep -Eq '^[[:space:]]*disabled_toolsets:[[:space:]]*\[\][[:space:]]*$' "${RENDERED}" \
    || die "web provider is available but rendered config did not enable web"
else
  grep -Eq '^[[:space:]]*disabled_toolsets:[[:space:]]*\[web\][[:space:]]*$' "${RENDERED}" \
    || die "web provider is unavailable but rendered config did not disable web"
fi

CHANGED=false
if ! cmp -s "${RENDERED}" "${DEPLOYED_CONFIG}"; then
  install -m 0640 -o "${HERMES_UID}" -g "${HERMES_GID}" "${RENDERED}" "${DEPLOYED_CONFIG}"
  CHANGED=true
  log "managed Hermes configuration updated"
else
  log "managed Hermes configuration already converged"
fi

if "${CHANGED}" && "${RESTART}" && docker inspect "${HERMES_CONTAINER}" >/dev/null 2>&1; then
  if [[ "$(docker inspect -f '{{.State.Running}}' "${HERMES_CONTAINER}")" == "true" ]]; then
    cd "${STACK_DIR}"
    docker compose up -d --no-deps --force-recreate hermes
    log "Hermes recreated; no other service was restarted"
  fi
fi

ENV_SHA256_AFTER="$(sha256sum "${ENV_FILE}" | awk '{print $1}')"
LOCK_SHA256_AFTER="$(sha256sum "${LOCK_FILE}" | awk '{print $1}')"
[[ "${ENV_SHA256_BEFORE}" == "${ENV_SHA256_AFTER}" ]] || die ".env changed during reconciliation"
[[ "${LOCK_SHA256_BEFORE}" == "${LOCK_SHA256_AFTER}" ]] || die ".lock changed during reconciliation"

if "${WEB_ENABLED}"; then
  log "result: web enabled exclusively through configured local SearXNG + Firecrawl"
else
  log "result: web disabled; no external fallback is permitted by managed config"
fi
