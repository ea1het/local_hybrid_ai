#!/usr/bin/env bash
set -Eeuo pipefail

STACK_NAME="stack4_-_gitea"
STACK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${STACK_DIR}/.env"
COMPOSE_FILE="${STACK_DIR}/docker-compose.yml"
LOCK_FILE="${STACK_DIR}/.lock"

log()  { printf '  %s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "docker no esta instalado"
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 no esta disponible"
[[ -f "${ENV_FILE}" ]] || die "falta ${ENV_FILE}"
[[ -f "${LOCK_FILE}" ]] || die "Stack4 no esta preparado: falta ${LOCK_FILE}; ejecuta primero ./01-prepare.sh"

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

require_env() { local key="$1"; [[ -n "${!key:-}" ]] || die "falta ${key} en ${ENV_FILE}"; }
for key in STACKS_ROOT BASE_PATH GITEA_DOMAIN GITEA_ROOT_URL GITEA_SSH_DOMAIN GITEA_SSH_PORT \
           GITEA_ADMIN_USERNAME GITEA_ADMIN_EMAIL GITEA_ADMIN_PASSWORD \
           GITEA_RUNNER_INSTANCE_URL GITEA_RUNNER_NAME; do
  require_env "${key}"
done

[[ "${STACK_DIR}" == "${STACKS_ROOT%/}/${STACK_NAME}" ]] || \
  die "este stack debe residir en ${STACKS_ROOT%/}/${STACK_NAME}; ruta actual: ${STACK_DIR}"

APP_INI="${BASE_PATH%/}/service_-_gitea/config/app.ini"
RUNNER_SERVICE="${BASE_PATH%/}/service_-_gitea-runner"
RUNNER_CONFIG="${RUNNER_SERVICE}/data/config.yaml"
RUNNER_TOKEN_FILE="${RUNNER_SERVICE}/secret/registration-token"
RUNNER_STATE_FILE="${RUNNER_SERVICE}/data/.runner"
[[ -f "${APP_INI}" ]] || die "falta ${APP_INI}; ejecuta primero ./01-prepare.sh"
[[ -f "${RUNNER_CONFIG}" ]] || die "falta ${RUNNER_CONFIG}; ejecuta primero ./01-prepare.sh"
[[ -s "${RUNNER_TOKEN_FILE}" ]] || die "falta el token runtime del runner; ejecuta primero ./01-prepare.sh"

compose=(docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}")

step "Validacion y descarga"
"${compose[@]}" config --quiet
"${compose[@]}" pull

step "Migraciones de Gitea"
"${compose[@]}" run --rm gitea gitea migrate --config /etc/gitea/app.ini

step "Usuario administrador"
if ! "${compose[@]}" run --rm gitea gitea admin user list --config /etc/gitea/app.ini --admin | grep -Fq "${GITEA_ADMIN_USERNAME}"; then
  "${compose[@]}" run --rm \
    -e GITEA_ADMIN_USERNAME -e GITEA_ADMIN_EMAIL -e GITEA_ADMIN_PASSWORD \
    gitea sh -ceu '
      gitea admin user create \
        --config /etc/gitea/app.ini \
        --username "$GITEA_ADMIN_USERNAME" \
        --email "$GITEA_ADMIN_EMAIL" \
        --password "$GITEA_ADMIN_PASSWORD" \
        --admin --must-change-password=false
    '
fi

step "Arranque"
"${compose[@]}" up -d

step "Validacion del runner"
for attempt in $(seq 1 30); do
  runner_running="$(docker inspect -f '{{.State.Running}}' gitea-runner 2>/dev/null || true)"
  if [[ "${runner_running}" == "true" && -s "${RUNNER_STATE_FILE}" ]]; then
    log "runner registrado con identidad persistente"
    break
  fi
  [[ "${attempt}" -lt 30 ]] || die "el runner no creo/recupero su identidad persistente"
  sleep 2
done

"${compose[@]}" ps

step "Instalacion terminada"
log "Gitea publico: ${GITEA_ROOT_URL}"
log "runner: ${GITEA_RUNNER_NAME}"
