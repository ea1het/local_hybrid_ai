#!/usr/bin/env bash
set -euo pipefail

STACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${STACK_DIR}/.env"

log() { printf '[issue-74116] %s\n' "$*"; }
die() { printf '[issue-74116] ERROR: %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run this script as root."
[[ -f "$ENV_FILE" ]] || die "Missing $ENV_FILE"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

[[ -n "${BASE_PATH:-}" ]] || die "BASE_PATH missing in .env"
[[ -n "${HERMES_SERVICE:-}" ]] || die "HERMES_SERVICE missing in .env"
[[ -n "${HERMES_CONTAINER:-}" ]] || die "HERMES_CONTAINER missing in .env"

RUNTIME_ENV="${BASE_PATH%/}/${HERMES_SERVICE}/data/.env"

cd "$STACK_DIR"

docker inspect "$HERMES_CONTAINER" >/dev/null 2>&1 || die "Container '$HERMES_CONTAINER' does not exist."
RUNNING="$(docker inspect --format '{{.State.Running}}' "$HERMES_CONTAINER")"
[[ "$RUNNING" == "true" ]] || die "Container '$HERMES_CONTAINER' is not running."
[[ -f "$RUNTIME_ENV" ]] || die "Hermes runtime .env does not exist: $RUNTIME_ENV"

TARGET_TIMEOUT="$(docker exec "$HERMES_CONTAINER" sh -c 'printf "%s" "$TERMINAL_TIMEOUT"')"
[[ "$TARGET_TIMEOUT" =~ ^[1-9][0-9]*$ ]] || die "Invalid TERMINAL_TIMEOUT from container: '$TARGET_TIMEOUT'"

MATCH_COUNT="$(grep -Ec '^(export[[:space:]]+)?TERMINAL_TIMEOUT=' "$RUNTIME_ENV" || true)"
[[ "$MATCH_COUNT" -eq 1 ]] || die "Expected exactly one TERMINAL_TIMEOUT in $RUNTIME_ENV; found $MATCH_COUNT"

CURRENT_TIMEOUT="$(sed -nE 's/^(export[[:space:]]+)?TERMINAL_TIMEOUT=(.*)$/\2/p' "$RUNTIME_ENV" | head -n1)"
log "Hermes runtime TERMINAL_TIMEOUT=$CURRENT_TIMEOUT"

if [[ "$CURRENT_TIMEOUT" != "$TARGET_TIMEOUT" ]]; then
  ORIGINAL_UID="$(stat -c '%u' "$RUNTIME_ENV")"
  ORIGINAL_GID="$(stat -c '%g' "$RUNTIME_ENV")"
  ORIGINAL_MODE="$(stat -c '%a' "$RUNTIME_ENV")"
  sed -i -E "s/^(export[[:space:]]+)?TERMINAL_TIMEOUT=.*/TERMINAL_TIMEOUT=${TARGET_TIMEOUT}/" "$RUNTIME_ENV"
  chown "${ORIGINAL_UID}:${ORIGINAL_GID}" "$RUNTIME_ENV"
  chmod "$ORIGINAL_MODE" "$RUNTIME_ENV"
fi

VALUE="$(sed -nE 's/^(export[[:space:]]+)?TERMINAL_TIMEOUT=(.*)$/\2/p' "$RUNTIME_ENV" | head -n1)"
[[ "$VALUE" == "$TARGET_TIMEOUT" ]] || die "Runtime .env verification failed before restart."

docker compose restart hermes

for _ in $(seq 1 60); do
  HEALTH="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$HERMES_CONTAINER" 2>/dev/null || true)"
  [[ "$HEALTH" == "healthy" ]] && break
  sleep 2
done

HEALTH="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$HERMES_CONTAINER")"
[[ "$HEALTH" == "healthy" ]] || die "Hermes did not become healthy. Current health: $HEALTH"

VALUE_AFTER_RESTART="$(sed -nE 's/^(export[[:space:]]+)?TERMINAL_TIMEOUT=(.*)$/\2/p' "$RUNTIME_ENV" | head -n1)"
[[ "$VALUE_AFTER_RESTART" == "$TARGET_TIMEOUT" ]] || die "Hermes rewrote TERMINAL_TIMEOUT after restart"

log "Temporary workaround applied successfully."
