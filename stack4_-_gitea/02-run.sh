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

if [[ -e "${LOCK_FILE}" ]]; then
  printf 'Stack ya preparado. Existe %s; no se realiza ningun cambio.\n' "${LOCK_FILE}"
  exit 0
fi

command -v docker >/dev/null 2>&1 || die "docker no esta instalado"
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 no esta disponible"
[[ -f "${ENV_FILE}" ]] || die "falta ${ENV_FILE}"

grep -Eq '^[A-Za-z_][A-Za-z0-9_]*=.*(<REDACT|\.{5,})' "${ENV_FILE}" && \
  die "${ENV_FILE} contiene valores saneados/incompletos; restaura los valores operativos antes de ejecutar el script"

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

require_env() { local key="$1"; [[ -n "${!key:-}" ]] || die "falta ${key} en ${ENV_FILE}"; }
for key in BASE_PATH GITEA_DOMAIN GITEA_ROOT_URL GITEA_SSH_DOMAIN GITEA_SSH_PORT \
           GITEA_ADMIN_USERNAME GITEA_ADMIN_EMAIL GITEA_ADMIN_PASSWORD \
           GITEA_RUNNER_INSTANCE_URL GITEA_RUNNER_REGISTRATION_TOKEN; do
  require_env "${key}"
done

[[ "${STACK_DIR}" == "${BASE_PATH}/${STACK_NAME}" ]] || \
  die "este stack debe residir en ${BASE_PATH}/${STACK_NAME}; ruta actual: ${STACK_DIR}"

APP_INI="${BASE_PATH}/service_-_gitea/config/app.ini"
RUNNER_CONFIG="${BASE_PATH}/service_-_gitea-runner/data/config.yaml"
[[ -f "${APP_INI}" ]] || die "falta ${APP_INI}; ejecuta primero ./01-prepare.sh"
[[ -f "${RUNNER_CONFIG}" ]] || die "falta ${RUNNER_CONFIG}; ejecuta primero ./01-prepare.sh"

compose=(docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}")

step "Validacion y descarga"
"${compose[@]}" config --quiet
"${compose[@]}" pull

step "Migraciones de Gitea"
"${compose[@]}" run --rm gitea gitea migrate --config /etc/gitea/app.ini

step "Usuario administrador"
if ! "${compose[@]}" run --rm gitea gitea admin user list --config /etc/gitea/app.ini --admin | grep -Fq "${GITEA_ADMIN_USERNAME}"; then
  "${compose[@]}" run --rm \
    -e GITEA_ADMIN_USERNAME \
    -e GITEA_ADMIN_EMAIL \
    -e GITEA_ADMIN_PASSWORD \
    gitea sh -ceu '
      gitea admin user create \
        --config /etc/gitea/app.ini \
        --username "$GITEA_ADMIN_USERNAME" \
        --email "$GITEA_ADMIN_EMAIL" \
        --password "$GITEA_ADMIN_PASSWORD" \
        --admin \
        --must-change-password=false
    '
  log "administrador creado"
else
  log "administrador ya existente"
fi

step "Arranque"
"${compose[@]}" up -d
"${compose[@]}" ps

{
  printf 'stack=%s\n' "${STACK_NAME}"
  printf 'prepared_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "${LOCK_FILE}"

step "Instalacion terminada"
log "Gitea publico: ${GITEA_ROOT_URL}"
log "Gitea interno: http://gitea:3000/"
log "lock creado: ${LOCK_FILE}"
