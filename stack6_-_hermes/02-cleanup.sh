#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

# =============================================================================
# Hermes Agent - controlled cleanup
#
# Usage:
#   ./02-cleanup.sh [--dry-run]
#   ./02-cleanup.sh --reset-state [--dry-run] [--yes]
#   ./02-cleanup.sh --factory-reset [--dry-run] [--yes]
#
# Modes:
#   default
#     Remove shadow configuration, stale runtime markers and regenerable caches.
#     Preserve sessions, auth state, memories, skills, cron, uploads and workspace.
#
#   --reset-state
#     Default cleanup + remove Hermes auth/session/routing databases and state.
#     Preserve user-facing persistent content such as memories, skills, cron,
#     uploads and sandbox workspace.
#
#   --factory-reset
#     Remove all mutable Hermes runtime/user state and sandbox home/workspace.
#     Preserve infrastructure managed outside runtime state:
#       - service_-_hermes/config/
#       - service_-_hermes-sandbox/config/
#       - service_-_hermes/data/bin/   (e.g. buzz CLI)
#
# Safety:
#   - must run as root
#   - stack .lock MUST already be absent
#   - hermes and hermes-sandbox containers MUST be stopped
#   - never modifies the stack .env
#   - never removes SSH keys or managed config/
# =============================================================================

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ENV_FILE="${SCRIPT_DIR}/.env"
LOCK_FILE="${SCRIPT_DIR}/.lock"

MODE="runtime"
DRY_RUN=0
ASSUME_YES=0

usage() {
    cat <<'EOF'
Usage:
  ./02-cleanup.sh [--dry-run]
  ./02-cleanup.sh --reset-state [--dry-run] [--yes]
  ./02-cleanup.sh --factory-reset [--dry-run] [--yes]

Options:
  --reset-state    Also remove auth/session/routing databases and state.
  --factory-reset  Remove all mutable Hermes state and sandbox workspace/home.
                   Preserves managed config/ and Hermes data/bin/.
  --dry-run        Show exactly what would be removed.
  --yes            Skip interactive confirmation for destructive modes.
  -h, --help       Show this help.
EOF
}

log()  { printf '[cleanup] %s\n' "$*"; }
warn() { printf '[cleanup] WARNING: %s\n' "$*" >&2; }
die()  { printf '[cleanup] ERROR: %s\n' "$*" >&2; exit 1; }

for arg in "$@"; do
    case "$arg" in
        --reset-state)
            [[ "$MODE" == "runtime" ]] || die "Choose only one cleanup mode."
            MODE="reset-state"
            ;;
        --factory-reset)
            [[ "$MODE" == "runtime" ]] || die "Choose only one cleanup mode."
            MODE="factory-reset"
            ;;
        --dry-run) DRY_RUN=1 ;;
        --yes) ASSUME_YES=1 ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unknown argument: $arg" ;;
    esac
done

[[ "$(id -u)" -eq 0 ]] || die "Must be run as root."

for cmd in docker realpath find rm stat grep basename id sha256sum awk; do
    command -v "$cmd" >/dev/null 2>&1 || die "Required command not found: $cmd"
done

# .lock is deliberately NOT removed here.
[[ ! -e "$LOCK_FILE" ]] || die \
    "Refusing cleanup while ${LOCK_FILE} exists. Stop the stack and remove .lock deliberately first."

[[ -f "$ENV_FILE" ]] || die "Missing ${ENV_FILE}"
ENV_SHA256_BEFORE="$(sha256sum -- "$ENV_FILE" | awk '{print $1}')"

# Read the already-defined stack environment. Never writes to it.
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

required_vars=(
    BASE_PATH
    HERMES_SERVICE
    SANDBOX_SERVICE
    HERMES_CONTAINER
    SANDBOX_CONTAINER
)
for var in "${required_vars[@]}"; do
    [[ -n "${!var:-}" ]] || die "Required variable ${var} is missing/empty in .env"
done

# Service names are expected to be simple directory names, never paths.
[[ "$HERMES_SERVICE" != */* ]] || die "HERMES_SERVICE must be a directory name, not a path."
[[ "$SANDBOX_SERVICE" != */* ]] || die "SANDBOX_SERVICE must be a directory name, not a path."
[[ "$HERMES_SERVICE" == service_-_* ]] || die "Unexpected HERMES_SERVICE: ${HERMES_SERVICE}"
[[ "$SANDBOX_SERVICE" == service_-_* ]] || die "Unexpected SANDBOX_SERVICE: ${SANDBOX_SERVICE}"

BASE_PATH_REAL="$(realpath -m -- "$BASE_PATH")"
HERMES_ROOT="$(realpath -m -- "${BASE_PATH_REAL}/${HERMES_SERVICE}")"
SANDBOX_ROOT="$(realpath -m -- "${BASE_PATH_REAL}/${SANDBOX_SERVICE}")"

HERMES_DATA="${HERMES_ROOT}/data"
HERMES_CONFIG="${HERMES_ROOT}/config"
HERMES_LOGS="${HERMES_ROOT}/logs"

SANDBOX_DATA="${SANDBOX_ROOT}/data"
SANDBOX_CONFIG="${SANDBOX_ROOT}/config"
SANDBOX_LOGS="${SANDBOX_ROOT}/logs"
SANDBOX_HOME="${SANDBOX_DATA}/home"
SANDBOX_WORKSPACE="${SANDBOX_DATA}/workspace"

# Hermes owns data/.env as persistent runtime state. Cleanup preserves it, but
# stack-managed routing/model/credential variables are forbidden there.
RUNTIME_ENV_ALLOWED_KEYS=(
    BROWSERBASE_ADVANCED_STEALTH
    BROWSERBASE_PROXIES
    BROWSER_INACTIVITY_TIMEOUT
    BROWSER_SESSION_TIMEOUT
    IMAGE_TOOLS_DEBUG
    MOA_TOOLS_DEBUG
    TERMINAL_LIFETIME_SECONDS
    TERMINAL_MODAL_IMAGE
    TERMINAL_TIMEOUT
    VISION_TOOLS_DEBUG
    WEB_TOOLS_DEBUG
)

runtime_env_key_allowed() {
    local candidate="$1"
    local allowed

    for allowed in "${RUNTIME_ENV_ALLOWED_KEYS[@]}"; do
        [[ "$candidate" == "$allowed" ]] && return 0
    done

    return 1
}

audit_runtime_env_safety() {
    local runtime_env="${HERMES_DATA}/.env"
    local key

    [[ -e "$runtime_env" || -L "$runtime_env" ]] || return 0

    [[ ! -L "$runtime_env" ]] \
        || die "Runtime .env must not be a symlink: ${runtime_env}"
    [[ -f "$runtime_env" ]] \
        || die "Runtime .env is not a regular file: ${runtime_env}"

    while IFS= read -r key; do
        [[ -n "$key" ]] || continue

        runtime_env_key_allowed "$key" && continue

        if grep -qE "^${key}=" "$ENV_FILE"; then
            die "Runtime .env redefines stack-managed variable: ${key}"
        fi
    done < <(
        sed -nE             's/^(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)=.*/\2/p'             "$runtime_env" |
        LC_ALL=C sort -u
    )
}

assert_service_root() {
    local path="$1"
    case "$path" in
        "${BASE_PATH_REAL}"/service_-_*) ;;
        *) die "Unsafe service path resolved outside expected service_-_* tree: ${path}" ;;
    esac
    [[ "$path" != "/" && "$path" != "$BASE_PATH_REAL" ]] || die "Unsafe cleanup path: ${path}"
}

assert_within() {
    local path resolved
    path="$1"
    resolved="$(realpath -m -- "$path")"
    case "$resolved" in
        "${HERMES_ROOT}"|"${HERMES_ROOT}"/*|"${SANDBOX_ROOT}"|"${SANDBOX_ROOT}"/*) ;;
        *) die "Refusing to touch path outside Hermes service trees: ${resolved}" ;;
    esac
}

assert_service_root "$HERMES_ROOT"
assert_service_root "$SANDBOX_ROOT"

container_running() {
    local name="$1"
    local running
    if ! docker inspect "$name" >/dev/null 2>&1; then
        return 1
    fi
    running="$(docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null || true)"
    [[ "$running" == "true" ]]
}

container_running "$HERMES_CONTAINER" &&
    die "Container ${HERMES_CONTAINER} is still running. Stop the stack first."
container_running "$SANDBOX_CONTAINER" &&
    die "Container ${SANDBOX_CONTAINER} is still running. Stop the stack first."

remove_path() {
    local path="$1"
    assert_within "$path"
    [[ -e "$path" || -L "$path" ]] || return 0
    if (( DRY_RUN )); then
        printf '  REMOVE  %s\n' "$path"
    else
        printf '  REMOVE  %s\n' "$path"
        rm -rf --one-file-system -- "$path" 2>/dev/null || rm -rf -- "$path"
    fi
}

remove_glob() {
    local pattern="$1"
    local match
    shopt -s nullglob
    # Intentional shell expansion of a trusted, script-defined pattern.
    # shellcheck disable=SC2086
    for match in $pattern; do
        remove_path "$match"
    done
    shopt -u nullglob
}

wipe_contents() {
    local dir="$1"
    local item
    assert_within "$dir"
    [[ -d "$dir" ]] || return 0

    while IFS= read -r -d '' item; do
        remove_path "$item"
    done < <(find "$dir" -mindepth 1 -maxdepth 1 -print0)
}

wipe_hermes_data_except_bin() {
    local item base
    [[ -d "$HERMES_DATA" ]] || return 0

    while IFS= read -r -d '' item; do
        base="$(basename -- "$item")"
        if [[ "$base" == "bin" ]]; then
            printf '  KEEP    %s\n' "$item"
            continue
        fi
        remove_path "$item"
    done < <(find "$HERMES_DATA" -mindepth 1 -maxdepth 1 -print0)
}

cleanup_runtime() {
    log "Removing shadow configuration and stale runtime artifacts."

    # Hermes-owned runtime .env and its backups are legitimate persistent
    # state. Preserve them, but reject stack-reserved variables.
    audit_runtime_env_safety

    # Only the active runtime config shadow is removed. Historical
    # config.yaml.bak-* files are preserved.
    remove_path "${HERMES_DATA}/config.yaml"
    remove_path "${HERMES_DATA}/.hermes"

    # Runtime markers/state that are safe to regenerate.
    remove_path "${HERMES_DATA}/gateway.pid"
    remove_path "${HERMES_DATA}/gateway.lock"
    remove_path "${HERMES_DATA}/gateway_state.json"
    remove_path "${HERMES_DATA}/gateway-starts.log"
    remove_path "${HERMES_DATA}/models_dev_cache.json"
    remove_path "${HERMES_DATA}/tui-theme-boot.json"
    remove_path "${HERMES_DATA}/processes.json"
    remove_path "${HERMES_DATA}/active_profile"
    remove_path "${HERMES_DATA}/.update_check"
    remove_path "${HERMES_DATA}/errors.log"

    # Regenerable caches documented/used by Hermes.
    remove_path "${HERMES_DATA}/image_cache"
    remove_path "${HERMES_DATA}/audio_cache"
    remove_path "${HERMES_DATA}/document_cache"
    remove_path "${HERMES_DATA}/browser_screenshots"
    remove_path "${HERMES_DATA}/checkpoints"
    remove_path "${HERMES_DATA}/sandboxes"

    # A shadow logs directory under data is masked by our dedicated logs bind.
    # Remove it if an older deployment created one.
    remove_path "${HERMES_DATA}/logs"
}

cleanup_state() {
    cleanup_runtime

    log "Removing Hermes auth/session/routing state."

    # Provider credentials / auth pools.
    remove_path "${HERMES_DATA}/auth.json"
    remove_path "${HERMES_DATA}/auth.lock"

    # Canonical and legacy session databases.
    remove_glob "${HERMES_DATA}/state.db*"
    remove_glob "${HERMES_DATA}/hermes_state.db*"
    remove_glob "${HERMES_DATA}/response_store.db*"

    # Gateway routing/session mirrors and transcripts.
    remove_path "${HERMES_DATA}/sessions"
    remove_path "${HERMES_DATA}/sessions.json"

    # Other routing/channel runtime metadata if present.
    remove_path "${HERMES_DATA}/channel_directory.json"
}

factory_reset() {
    log "Factory reset: removing all mutable Hermes data except data/bin/."
    wipe_hermes_data_except_bin

    log "Factory reset: clearing Hermes logs."
    wipe_contents "$HERMES_LOGS"

    log "Factory reset: clearing sandbox mutable home/workspace."
    wipe_contents "$SANDBOX_HOME"
    wipe_contents "$SANDBOX_WORKSPACE"

    log "Factory reset: clearing sandbox logs."
    wipe_contents "$SANDBOX_LOGS"

    printf '\n'
    printf '  KEEP    %s\n' "$HERMES_CONFIG"
    printf '  KEEP    %s\n' "$SANDBOX_CONFIG"
    printf '  KEEP    %s\n' "${HERMES_DATA}/bin"
}

confirm_destructive_mode() {
    [[ "$MODE" == "runtime" ]] && return 0
    (( ASSUME_YES )) && return 0
    (( DRY_RUN )) && return 0

    [[ -t 0 ]] || die "Mode ${MODE} requires --yes when stdin is not interactive."

    printf '\n'
    warn "Mode '${MODE}' is destructive."
    if [[ "$MODE" == "reset-state" ]]; then
        warn "Pairing, home-channel routing, provider auth and session history will be reset."
    else
        warn "All mutable Hermes data, logs, sandbox home and sandbox workspace will be erased."
        warn "Managed config/ directories and Hermes data/bin/ will be preserved."
    fi
    printf 'Type CLEAN to continue: '
    local answer
    read -r answer
    [[ "$answer" == "CLEAN" ]] || die "Cancelled."
}

audit_after_cleanup() {
    (( DRY_RUN )) && return 0

    local unexpected=0
    local env_sha256_after
    env_sha256_after="$(sha256sum -- "$ENV_FILE" | awk '{print $1}')"
    if [[ "$env_sha256_after" != "$ENV_SHA256_BEFORE" ]]; then
        printf '[cleanup] AUDIT FAIL: stack .env changed during cleanup: %s\n' "$ENV_FILE" >&2
        unexpected=1
    fi
    local forbidden_runtime=(
        "${HERMES_DATA}/.hermes"
        "${HERMES_DATA}/config.yaml"
        "${HERMES_DATA}/gateway.pid"
        "${HERMES_DATA}/gateway.lock"
        "${HERMES_DATA}/gateway_state.json"
        "${HERMES_DATA}/models_dev_cache.json"
    )

    for path in "${forbidden_runtime[@]}"; do
        if [[ -e "$path" || -L "$path" ]]; then
            printf '[cleanup] AUDIT FAIL: still exists: %s\n' "$path" >&2
            unexpected=1
        fi
    done

    # Preserved runtime dotenv must remain within the same safety contract.
    audit_runtime_env_safety

    if [[ "$MODE" == "reset-state" ]]; then
        for path in \
            "${HERMES_DATA}/auth.json" \
            "${HERMES_DATA}/state.db" \
            "${HERMES_DATA}/sessions"
        do
            if [[ -e "$path" || -L "$path" ]]; then
                printf '[cleanup] AUDIT FAIL: still exists: %s\n' "$path" >&2
                unexpected=1
            fi
        done
    fi

    if [[ "$MODE" == "factory-reset" ]]; then
        if [[ -d "$HERMES_DATA" ]]; then
            while IFS= read -r -d '' path; do
                [[ "$(basename -- "$path")" == "bin" ]] && continue
                printf '[cleanup] AUDIT FAIL: unexpected Hermes data remains: %s\n' "$path" >&2
                unexpected=1
            done < <(find "$HERMES_DATA" -mindepth 1 -maxdepth 1 -print0)
        fi

        for dir in "$HERMES_LOGS" "$SANDBOX_HOME" "$SANDBOX_WORKSPACE" "$SANDBOX_LOGS"; do
            if [[ -d "$dir" ]] && find "$dir" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
                printf '[cleanup] AUDIT FAIL: directory is not empty: %s\n' "$dir" >&2
                unexpected=1
            fi
        done
    fi

    (( unexpected == 0 )) || die "Post-cleanup audit failed."
    log "Post-cleanup audit: OK"
}

printf '\n'
log "Hermes cleanup plan"
printf '  MODE        %s\n' "$MODE"
printf '  DRY_RUN     %s\n' "$DRY_RUN"
printf '  STACK       %s\n' "$SCRIPT_DIR"
printf '  HERMES      %s\n' "$HERMES_ROOT"
printf '  SANDBOX     %s\n' "$SANDBOX_ROOT"
printf '  PRESERVE    %s\n' "$HERMES_CONFIG"
printf '  PRESERVE    %s\n' "$SANDBOX_CONFIG"
printf '  PRESERVE    %s\n' "${HERMES_DATA}/bin"
printf '\n'

confirm_destructive_mode

case "$MODE" in
    runtime)       cleanup_runtime ;;
    reset-state)   cleanup_state ;;
    factory-reset) factory_reset ;;
    *) die "Internal error: unknown mode ${MODE}" ;;
esac

audit_after_cleanup

printf '\n'
if (( DRY_RUN )); then
    log "Dry-run complete. Nothing was removed."
else
    log "Cleanup complete."
fi
