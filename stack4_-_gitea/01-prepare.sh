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

[[ "$(id -u)" -eq 0 ]] || die "ejecuta este script como root"
command -v docker >/dev/null 2>&1 || die "docker no esta instalado"
command -v sed >/dev/null 2>&1 || die "sed no esta instalado"
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 no esta disponible"
[[ -f "${ENV_FILE}" ]] || die "falta ${ENV_FILE}"
[[ -f "${COMPOSE_FILE}" ]] || die "falta ${COMPOSE_FILE}"

grep -Eq '^[A-Za-z_][A-Za-z0-9_]*=.*(<REDACT|\.{5,})' "${ENV_FILE}" && \
  die "${ENV_FILE} contiene valores saneados/incompletos; restaura los valores operativos antes de ejecutar el script"

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

require_env() { local key="$1"; [[ -n "${!key:-}" ]] || die "falta ${key} en ${ENV_FILE}"; }
for key in BASE_PATH GITEA_IMAGE GITEA_CONTAINER_NAME GITEA_UID GITEA_GID \
           GITEA_SSH_BIND GITEA_SSH_PORT GITEA_DOCKER_NETWORK GITEA_DOMAIN \
           GITEA_ROOT_URL GITEA_SSH_DOMAIN GITEA_TIMEZONE GITEA_INTERNAL_TOKEN \
           GITEA_JWT_SECRET GITEA_ADMIN_USERNAME GITEA_ADMIN_EMAIL GITEA_ADMIN_PASSWORD \
           GITEA_RUNNER_IMAGE GITEA_RUNNER_NAME GITEA_RUNNER_INSTANCE_URL \
           GITEA_RUNNER_REGISTRATION_TOKEN; do
  require_env "${key}"
done

[[ "${BASE_PATH}" = /* ]] || die "BASE_PATH debe ser una ruta absoluta"
[[ "${STACK_DIR}" == "${BASE_PATH}/${STACK_NAME}" ]] || \
  die "este stack debe residir en ${BASE_PATH}/${STACK_NAME}; ruta actual: ${STACK_DIR}"
[[ "${GITEA_ROOT_URL}" == "https://${GITEA_DOMAIN}/" ]] || \
  die "GITEA_ROOT_URL debe ser https://${GITEA_DOMAIN}/"
[[ "${GITEA_RUNNER_INSTANCE_URL}" == "http://gitea:3000/" ]] || \
  die "GITEA_RUNNER_INSTANCE_URL debe ser http://gitea:3000/"

GITEA_SERVICE="${BASE_PATH}/service_-_gitea"
RUNNER_SERVICE="${BASE_PATH}/service_-_gitea-runner"
LEGACY_ROOT="${BASE_PATH}/gitea"
APP_SOURCE="${STACK_DIR}/config/gitea/app.ini"
RUNNER_SOURCE="${STACK_DIR}/config/gitea-runner/config.yaml"
APP_TARGET="${GITEA_SERVICE}/config/app.ini"
RUNNER_TARGET="${RUNNER_SERVICE}/data/config.yaml"

[[ -f "${APP_SOURCE}" ]] || die "falta ${APP_SOURCE}"
[[ -f "${RUNNER_SOURCE}" ]] || die "falta ${RUNNER_SOURCE}"

step "Migracion de datos antiguos"
mkdir -p "${GITEA_SERVICE}" "${RUNNER_SERVICE}"

if [[ -e "${LEGACY_ROOT}/data" && -e "${GITEA_SERVICE}/data" ]]; then
  die "existen simultaneamente ${LEGACY_ROOT}/data y ${GITEA_SERVICE}/data; resuelve manualmente la migracion"
elif [[ -e "${LEGACY_ROOT}/data" ]]; then
  mv "${LEGACY_ROOT}/data" "${GITEA_SERVICE}/data"
  log "datos Gitea migrados"
fi

if [[ -e "${LEGACY_ROOT}/runner" && -e "${RUNNER_SERVICE}/data" ]]; then
  die "existen simultaneamente ${LEGACY_ROOT}/runner y ${RUNNER_SERVICE}/data; resuelve manualmente la migracion"
elif [[ -e "${LEGACY_ROOT}/runner" ]]; then
  mv "${LEGACY_ROOT}/runner" "${RUNNER_SERVICE}/data"
  log "estado del runner migrado"
fi

mkdir -p "${GITEA_SERVICE}/data" "${RUNNER_SERVICE}/data"

step "Red Docker ${GITEA_DOCKER_NETWORK}"
if docker network inspect "${GITEA_DOCKER_NETWORK}" >/dev/null 2>&1; then
  driver="$(docker network inspect -f '{{.Driver}}' "${GITEA_DOCKER_NETWORK}")"
  [[ "${driver}" == "bridge" ]] || die "${GITEA_DOCKER_NETWORK} existe pero usa driver ${driver}, no bridge"
  log "existe y es bridge"
else
  docker network create --driver bridge "${GITEA_DOCKER_NETWORK}" >/dev/null
  log "creada"
fi

escape_sed_replacement() {
  printf '%s' "$1" | sed 's/[\\&|]/\\&/g'
}

render_file() {
  local source="$1" target="$2"
  shift 2
  local tmp="${target}.tmp.$$"
  cp "${source}" "${tmp}"
  while [[ "$#" -gt 0 ]]; do
    local token="$1" value="$2" escaped
    shift 2
    escaped="$(escape_sed_replacement "${value}")"
    sed -i "s|@@${token}@@|${escaped}|g" "${tmp}"
  done
  if grep -q '@@[A-Za-z0-9_][A-Za-z0-9_]*@@' "${tmp}"; then
    rm -f "${tmp}"
    die "han quedado placeholders sin resolver al renderizar ${source}"
  fi
  mv "${tmp}" "${target}"
}

step "Configuracion de Gitea"
rm -rf "${GITEA_SERVICE}/config"
mkdir -p "${GITEA_SERVICE}/config"
render_file "${APP_SOURCE}" "${APP_TARGET}" \
  GITEA_DOMAIN "${GITEA_DOMAIN}" \
  GITEA_ROOT_URL "${GITEA_ROOT_URL}" \
  GITEA_SSH_DOMAIN "${GITEA_SSH_DOMAIN}" \
  GITEA_SSH_PORT "${GITEA_SSH_PORT}" \
  GITEA_INTERNAL_TOKEN "${GITEA_INTERNAL_TOKEN}" \
  GITEA_JWT_SECRET "${GITEA_JWT_SECRET}"
chmod 0640 "${APP_TARGET}"
chown -R "${GITEA_UID}:${GITEA_GID}" "${GITEA_SERVICE}/config" "${GITEA_SERVICE}/data"
log "app.ini reescrito desde el fichero del stack"

step "Configuracion del runner"
# Estos ficheros pertenecen a la antigua estrategia TLS del runner y ya no se usan.
rm -f "${RUNNER_SERVICE}/data/ca-certificates.crt" "${RUNNER_SERVICE}/data/certificates.txt"
render_file "${RUNNER_SOURCE}" "${RUNNER_TARGET}" \
  GITEA_DOCKER_NETWORK "${GITEA_DOCKER_NETWORK}"
chmod 0640 "${RUNNER_TARGET}"
chown -R "${GITEA_UID}:${GITEA_GID}" "${RUNNER_SERVICE}/data"
log "runner configurado para http://gitea:3000/ por ${GITEA_DOCKER_NETWORK}"

# La configuracion antigua ya no es operativa. Los datos persistentes se han movido arriba.
if [[ -d "${LEGACY_ROOT}/config" ]]; then
  rm -rf "${LEGACY_ROOT}/config"
fi
rmdir "${LEGACY_ROOT}" 2>/dev/null || true

step "Validacion de Docker Compose"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" config --quiet
log "compose valido"

step "Paso 1 terminado"
log "ejecuta ./02-run.sh para migrar Gitea, asegurar el administrador y arrancar el stack"
