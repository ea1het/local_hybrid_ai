#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Temporary workaround for Hermes issue #74116
#
# https://github.com/NousResearch/hermes-agent/issues/74116
#
# Hermes gateway currently fails to bridge terminal.timeout from config.yaml
# to TERMINAL_TIMEOUT correctly. The runtime-generated /opt/data/.env may
# therefore retain TERMINAL_TIMEOUT=60.
#
# This script synchronizes that runtime value with the TERMINAL_TIMEOUT
# already supplied to the container by Docker Compose.
#
# DELETE THIS SCRIPT once upstream issue #74116 is fixed and verified.
# ---------------------------------------------------------------------------

STACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_CONTAINER="hermes"
RUNTIME_ENV="/opt/docker/service_-_hermes/data/.env"

log() {
    printf '[issue-74116] %s\n' "$*"
}

die() {
    printf '[issue-74116] ERROR: %s\n' "$*" >&2
    exit 1
}

# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------

[[ $EUID -eq 0 ]] || die "Run this script as root."

cd "$STACK_DIR"

docker inspect "$HERMES_CONTAINER" >/dev/null 2>&1 \
    || die "Container '$HERMES_CONTAINER' does not exist."

RUNNING="$(
    docker inspect \
        --format '{{.State.Running}}' \
        "$HERMES_CONTAINER"
)"

[[ "$RUNNING" == "true" ]] \
    || die "Container '$HERMES_CONTAINER' is not running."

[[ -f "$RUNTIME_ENV" ]] \
    || die "Hermes runtime .env does not exist: $RUNTIME_ENV"

# ---------------------------------------------------------------------------
# Obtain desired value from the Docker environment.
#
# This deliberately avoids hardcoding 300 here. The stack .env remains
# the single source of truth.
# ---------------------------------------------------------------------------

TARGET_TIMEOUT="$(
    docker exec "$HERMES_CONTAINER" \
        sh -c 'printf "%s" "$TERMINAL_TIMEOUT"'
)"

[[ "$TARGET_TIMEOUT" =~ ^[1-9][0-9]*$ ]] \
    || die "Invalid TERMINAL_TIMEOUT from container: '$TARGET_TIMEOUT'"

log "Docker environment TERMINAL_TIMEOUT=$TARGET_TIMEOUT"

# ---------------------------------------------------------------------------
# Validate runtime file before modifying it.
# ---------------------------------------------------------------------------

MATCH_COUNT="$(
    grep -Ec '^(export[[:space:]]+)?TERMINAL_TIMEOUT=' "$RUNTIME_ENV" || true
)"

[[ "$MATCH_COUNT" -eq 1 ]] \
    || die "Expected exactly one TERMINAL_TIMEOUT in $RUNTIME_ENV; found $MATCH_COUNT"

CURRENT_TIMEOUT="$(
    sed -nE \
        's/^(export[[:space:]]+)?TERMINAL_TIMEOUT=(.*)$/\2/p' \
        "$RUNTIME_ENV" |
    head -n1
)"

log "Hermes runtime TERMINAL_TIMEOUT=$CURRENT_TIMEOUT"

if [[ "$CURRENT_TIMEOUT" == "$TARGET_TIMEOUT" ]]; then
    log "Runtime value already matches Docker environment."
else
    log "Applying temporary workaround: $CURRENT_TIMEOUT -> $TARGET_TIMEOUT"

    ORIGINAL_UID="$(stat -c '%u' "$RUNTIME_ENV")"
    ORIGINAL_GID="$(stat -c '%g' "$RUNTIME_ENV")"
    ORIGINAL_MODE="$(stat -c '%a' "$RUNTIME_ENV")"

    sed -i -E \
        "s/^(export[[:space:]]+)?TERMINAL_TIMEOUT=.*/TERMINAL_TIMEOUT=${TARGET_TIMEOUT}/" \
        "$RUNTIME_ENV"

    chown "${ORIGINAL_UID}:${ORIGINAL_GID}" "$RUNTIME_ENV"
    chmod "$ORIGINAL_MODE" "$RUNTIME_ENV"
fi

# ---------------------------------------------------------------------------
# Verify before restart.
# ---------------------------------------------------------------------------

VALUE="$(
    sed -nE \
        's/^(export[[:space:]]+)?TERMINAL_TIMEOUT=(.*)$/\2/p' \
        "$RUNTIME_ENV" |
    head -n1
)"

[[ "$VALUE" == "$TARGET_TIMEOUT" ]] \
    || die "Runtime .env verification failed before restart."

log "Runtime .env now contains TERMINAL_TIMEOUT=$VALUE"

# ---------------------------------------------------------------------------
# Restart Hermes so the gateway reloads /opt/data/.env.
#
# Only Hermes is restarted. The sandbox does not need restarting for this
# workaround.
# ---------------------------------------------------------------------------

log "Restarting Hermes..."

docker compose restart hermes

# ---------------------------------------------------------------------------
# Wait for health.
# ---------------------------------------------------------------------------

log "Waiting for Hermes health..."

for _ in $(seq 1 60); do
    HEALTH="$(
        docker inspect \
            --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \
            "$HERMES_CONTAINER" 2>/dev/null || true
    )"

    if [[ "$HEALTH" == "healthy" ]]; then
        break
    fi

    sleep 2
done

HEALTH="$(
    docker inspect \
        --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \
        "$HERMES_CONTAINER"
)"

[[ "$HEALTH" == "healthy" ]] \
    || die "Hermes did not become healthy. Current health: $HEALTH"

log "Hermes is healthy."

# ---------------------------------------------------------------------------
# Verify Hermes did not overwrite the workaround during startup.
# ---------------------------------------------------------------------------

VALUE_AFTER_RESTART="$(
    sed -nE \
        's/^(export[[:space:]]+)?TERMINAL_TIMEOUT=(.*)$/\2/p' \
        "$RUNTIME_ENV" |
    head -n1
)"

[[ "$VALUE_AFTER_RESTART" == "$TARGET_TIMEOUT" ]] || {
    die "Hermes rewrote TERMINAL_TIMEOUT after restart: expected $TARGET_TIMEOUT, found $VALUE_AFTER_RESTART"
}

log "Post-restart verification: TERMINAL_TIMEOUT=$VALUE_AFTER_RESTART"
log "Temporary workaround for Hermes issue #74116 applied successfully."
