#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

# Reconcile optional Stack6 capabilities without changing PREPARED state.
#
# Capabilities:
#   web.search + web.extract
#     provider: local SearXNG + Firecrawl on NETWORK_NAME
#     absent/incomplete provider => Hermes web toolset remains disabled
#
#   git.remote
#     provider: local Gitea on NETWORK_NAME
#     consumer: hermes-memory-sync profile
#     activation requires explicit persistent operator intent plus a previously
#     adopted/validated Git memory working tree and dedicated SSH material.
#     provider disappearance stops only the memory-sync sidecar; local memory
#     and Git state are preserved for safe later resumption.
#
# This script never creates provider resources, adopts/clones Git memory, makes
# Git commits, pushes, pulls, merges, rebases or changes .env/.lock.

STACK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ENV_FILE="${STACK_DIR}/.env"
LOCK_FILE="${STACK_DIR}/.lock"
SOURCE_CONFIG="${STACK_DIR}/config/hermes/config.yaml"
RESTART=false
GIT_MEMORY_ACTION="preserve"

log()  { printf '[capabilities] %s\n' "$*"; }
warn() { printf '[capabilities] WARNING: %s\n' "$*" >&2; }
die()  { printf '[capabilities] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage: 06-reconcile-capabilities.sh [--restart] [--enable-git-memory|--disable-git-memory]

  --restart             recreate only Hermes when its managed config changes
                        and Hermes is already running.
  --enable-git-memory   persist operator intent to consume git.remote and start
                        the memory-sync sidecar only when safe preconditions hold.
  --disable-git-memory  persist operator intent to disable Git-backed memory and
                        stop only the memory-sync sidecar if it is running.

Without a Git-memory flag, the previously persisted intent is preserved. A new
Stack6 deployment defaults to Git-memory disabled.
EOF
}

while (($#)); do
  case "$1" in
    --restart) RESTART=true ;;
    --enable-git-memory)
      [[ "${GIT_MEMORY_ACTION}" == "preserve" ]] || die "Git-memory intent flags are mutually exclusive"
      GIT_MEMORY_ACTION="enable"
      ;;
    --disable-git-memory)
      [[ "${GIT_MEMORY_ACTION}" == "preserve" ]] || die "Git-memory intent flags are mutually exclusive"
      GIT_MEMORY_ACTION="disable"
      ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
  shift
done

[[ "$(id -u)" -eq 0 ]] || die "run as root"
for cmd in docker awk grep install cmp mktemp sha256sum git sort; do
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

required=(BASE_PATH NETWORK_NAME HERMES_SERVICE HERMES_CONTAINER HERMES_UID HERMES_GID HERMES_MODEL HERMES_MEMORY_SERVICE MEMORY_SYNC_SERVICE MEMORY_SYNC_CONTAINER)
for key in "${required[@]}"; do
  [[ -n "${!key:-}" ]] || die "missing ${key} in .env"
done

[[ "${BASE_PATH}" == /* ]] || die "BASE_PATH must be absolute"
DEPLOYED_CONFIG="${BASE_PATH%/}/${HERMES_SERVICE}/config/config.yaml"
MEMORY_DIR="${BASE_PATH%/}/${HERMES_MEMORY_SERVICE}/data"
MEMORY_SYNC_DIR="${BASE_PATH%/}/${MEMORY_SYNC_SERVICE}"
MEMORY_SYNC_SSH_DIR="${MEMORY_SYNC_DIR}/ssh"
GIT_MEMORY_STATE_FILE="${MEMORY_SYNC_DIR}/desired-state"
[[ -f "${DEPLOYED_CONFIG}" && ! -L "${DEPLOYED_CONFIG}" ]] || die "invalid deployed config: ${DEPLOYED_CONFIG}"

container_ready_on_network() {
  local container="$1" running attached
  docker inspect "${container}" >/dev/null 2>&1 || return 1
  running="$(docker inspect -f '{{.State.Running}}' "${container}")"
  [[ "${running}" == "true" ]] || return 1
  attached="$(docker inspect -f "{{if index .NetworkSettings.Networks \"${NETWORK_NAME}\"}}yes{{else}}no{{end}}" "${container}")"
  [[ "${attached}" == "yes" ]]
}

container_running() {
  local container="$1"
  docker inspect "${container}" >/dev/null 2>&1 || return 1
  [[ "$(docker inspect -f '{{.State.Running}}' "${container}")" == "true" ]]
}

stop_memory_sync_if_running() {
  if container_running "${MEMORY_SYNC_CONTAINER}"; then
    docker stop "${MEMORY_SYNC_CONTAINER}" >/dev/null
    log "Git-memory sidecar stopped; no other Stack6 service was changed"
  fi
}

# ---------------------------------------------------------------------------
# web.search + web.extract
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# git.remote -> hermes-memory-sync
# ---------------------------------------------------------------------------
install -d -m 0750 -o "${HERMES_UID}" -g "${HERMES_GID}" "${MEMORY_SYNC_DIR}"

case "${GIT_MEMORY_ACTION}" in
  enable)
    printf 'enabled\n' > "${GIT_MEMORY_STATE_FILE}.tmp"
    chown "${HERMES_UID}:${HERMES_GID}" "${GIT_MEMORY_STATE_FILE}.tmp"
    chmod 0640 "${GIT_MEMORY_STATE_FILE}.tmp"
    mv "${GIT_MEMORY_STATE_FILE}.tmp" "${GIT_MEMORY_STATE_FILE}"
    ;;
  disable)
    printf 'disabled\n' > "${GIT_MEMORY_STATE_FILE}.tmp"
    chown "${HERMES_UID}:${HERMES_GID}" "${GIT_MEMORY_STATE_FILE}.tmp"
    chmod 0640 "${GIT_MEMORY_STATE_FILE}.tmp"
    mv "${GIT_MEMORY_STATE_FILE}.tmp" "${GIT_MEMORY_STATE_FILE}"
    ;;
  preserve) ;;
esac

GIT_MEMORY_DESIRED="disabled"
if [[ -f "${GIT_MEMORY_STATE_FILE}" && ! -L "${GIT_MEMORY_STATE_FILE}" ]]; then
  read -r GIT_MEMORY_DESIRED < "${GIT_MEMORY_STATE_FILE}" || true
fi
[[ "${GIT_MEMORY_DESIRED}" == "enabled" || "${GIT_MEMORY_DESIRED}" == "disabled" ]] \
  || die "invalid Git-memory desired state in ${GIT_MEMORY_STATE_FILE}"

GITEA_PROVIDER_CONTAINER="${GITEA_CONTAINER_NAME:-gitea}"
GIT_REMOTE_AVAILABLE=false
if container_ready_on_network "${GITEA_PROVIDER_CONTAINER}"; then
  GIT_REMOTE_AVAILABLE=true
  log "git.remote: available"
else
  log "git.remote: unavailable"
fi

if [[ "${GIT_MEMORY_DESIRED}" == "disabled" ]]; then
  stop_memory_sync_if_running
  log "Git-memory: disabled by operator intent"
elif ! "${GIT_REMOTE_AVAILABLE}"; then
  stop_memory_sync_if_running
  log "Git-memory: requested but provider unavailable; local memory/Git state preserved"
else
  [[ -n "${GITMEM_REPOSITORY:-}" && "${GITMEM_REPOSITORY}" != PUT_YOUR_* ]] \
    || die "Git-memory is enabled but GITMEM_REPOSITORY is not configured"
  [[ -n "${GITMEM_BRANCH:-}" ]] || die "Git-memory is enabled but GITMEM_BRANCH is empty"
  [[ -d "${MEMORY_DIR}/.git" ]] || die "Git-memory is enabled but working tree is not adopted; run 04-gitmem.sh safely first"
  [[ -f "${MEMORY_DIR}/MEMORY.md" && ! -L "${MEMORY_DIR}/MEMORY.md" ]] || die "invalid MEMORY.md in adopted Git-memory working tree"
  [[ -f "${MEMORY_DIR}/USER.md" && ! -L "${MEMORY_DIR}/USER.md" ]] || die "invalid USER.md in adopted Git-memory working tree"
  for ssh_file in ssh_config id_ed25519 known_hosts; do
    [[ -s "${MEMORY_SYNC_SSH_DIR}/${ssh_file}" && ! -L "${MEMORY_SYNC_SSH_DIR}/${ssh_file}" ]] \
      || die "Git-memory is enabled but dedicated SSH material is incomplete; run 05-maintenance-sidecars.sh first"
  done

  if container_running "${MEMORY_SYNC_CONTAINER}"; then
    log "Git-memory: enabled and sidecar already running"
  else
    LOCAL_HEAD="$(git -c safe.directory="${MEMORY_DIR}" -C "${MEMORY_DIR}" rev-parse HEAD)"
    [[ -z "$(git -c safe.directory="${MEMORY_DIR}" -C "${MEMORY_DIR}" status --porcelain)" ]] \
      || die "Git-memory working tree is dirty; refusing to start sidecar automatically"
    [[ "$(git -c safe.directory="${MEMORY_DIR}" -C "${MEMORY_DIR}" branch --show-current)" == "${GITMEM_BRANCH}" ]] \
      || die "Git-memory local branch does not match GITMEM_BRANCH"

    cd "${STACK_DIR}"
    docker compose --profile git-memory build hermes-memory-sync >/dev/null
    REMOTE_RAW="$(
      docker compose --profile git-memory run --rm --no-deps --entrypoint bash hermes-memory-sync -lc '
        export GIT_SSH_COMMAND="ssh -F /run/hermes-memory-ssh/ssh_config"
        git -c safe.directory=/work/hermes-memory -C /work/hermes-memory ls-remote origin "refs/heads/${MEMORY_SYNC_BRANCH}"
      '
    )" || die "read-only Git-memory remote preflight failed"
    REMOTE_HEAD="$(printf '%s\n' "${REMOTE_RAW}" | awk -v ref="refs/heads/${GITMEM_BRANCH}" '$2 == ref {print $1; exit}')"
    [[ -n "${REMOTE_HEAD}" ]] || die "Git-memory remote branch ${GITMEM_BRANCH} is unavailable"
    [[ "${LOCAL_HEAD}" == "${REMOTE_HEAD}" ]] \
      || die "Git-memory local/remote HEAD differ; refusing automatic sidecar start"

    docker compose --profile git-memory up -d --no-deps hermes-memory-sync
    log "Git-memory: enabled; sidecar started after clean local/remote equality preflight"
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
log "result: Git-memory desired=${GIT_MEMORY_DESIRED}, git.remote=$([[ "${GIT_REMOTE_AVAILABLE}" == true ]] && printf available || printf unavailable)"
