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
for cmd in docker sed openssl install ln readlink; do
  command -v "${cmd}" >/dev/null 2>&1 || die "falta el comando requerido: ${cmd}"
done
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 no esta disponible"
[[ -f "${ENV_FILE}" ]] || die "falta ${ENV_FILE}"
[[ -f "${COMPOSE_FILE}" ]] || die "falta ${COMPOSE_FILE}"

grep -Eq '^[A-Za-z_][A-Za-z0-9_]*=.*(<REDACT|\.{5,})' "${ENV_FILE}" && die "${ENV_FILE} contiene valores saneados/incompletos"

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

require_env() { local key="$1"; [[ -n "${!key:-}" ]] || die "falta ${key} en ${ENV_FILE}"; }
for key in STACKS_ROOT BASE_PATH NETWORK_NAME GITEA_IMAGE GITEA_CONTAINER_NAME GITEA_UID GITEA_GID \
           GITEA_SSH_BIND GITEA_SSH_PORT GITEA_DOCKER_NETWORK GITEA_DOMAIN \
           GITEA_ROOT_URL GITEA_SSH_DOMAIN GITEA_TIMEZONE GITEA_INTERNAL_TOKEN \
           GITEA_JWT_SECRET GITEA_ADMIN_USERNAME GITEA_ADMIN_EMAIL GITEA_ADMIN_PASSWORD \
           GITEA_RUNNER_IMAGE GITEA_RUNNER_NAME GITEA_RUNNER_INSTANCE_URL; do
  require_env "${key}"
done

[[ "${STACKS_ROOT}" = /* && "${BASE_PATH}" = /* ]] || die "STACKS_ROOT y BASE_PATH deben ser rutas absolutas"
[[ "${STACK_DIR}" == "${STACKS_ROOT%/}/${STACK_NAME}" ]] || \
  die "este stack debe residir en ${STACKS_ROOT%/}/${STACK_NAME}; ruta actual: ${STACK_DIR}"
[[ "${STACKS_ROOT%/}" != "${BASE_PATH%/}" ]] || die "STACKS_ROOT y BASE_PATH deben ser distintos"
[[ "${GITEA_ROOT_URL}" == "https://${GITEA_DOMAIN}/" ]] || die "GITEA_ROOT_URL debe ser https://${GITEA_DOMAIN}/"
[[ "${GITEA_RUNNER_INSTANCE_URL}" == "http://gitea:3000/" ]] || die "GITEA_RUNNER_INSTANCE_URL debe ser http://gitea:3000/"
[[ "${GITEA_DOCKER_NETWORK}" == "${NETWORK_NAME}" ]] || die "GITEA_DOCKER_NETWORK debe coincidir con NETWORK_NAME (${NETWORK_NAME})"

GITEA_SERVICE="${BASE_PATH%/}/service_-_gitea"
RUNNER_SERVICE="${BASE_PATH%/}/service_-_gitea-runner"
RUNNER_SECRET_DIR="${RUNNER_SERVICE}/secret"
RUNNER_TOKEN_FILE="${RUNNER_SECRET_DIR}/registration-token"
APP_SOURCE="${STACK_DIR}/config/gitea/app.ini"
RUNNER_SOURCE="${STACK_DIR}/config/gitea-runner/config.yaml"
APP_TARGET="${GITEA_SERVICE}/config/app.ini"
APP_DEFAULT_TARGET="${GITEA_SERVICE}/config/conf/app.ini"
RUNNER_TARGET="${RUNNER_SERVICE}/data/config.yaml"

[[ -f "${APP_SOURCE}" ]] || die "falta ${APP_SOURCE}"
[[ -f "${RUNNER_SOURCE}" ]] || die "falta ${RUNNER_SOURCE}"
install -d -m 0750 "${BASE_PATH}" "${GITEA_SERVICE}/data" "${RUNNER_SERVICE}/data"
install -d -m 0750 -o 0 -g "${GITEA_GID}" "${RUNNER_SECRET_DIR}"

step "Red Docker compartida ${GITEA_DOCKER_NETWORK}"
docker network inspect "${GITEA_DOCKER_NETWORK}" >/dev/null 2>&1 || \
  die "falta ${GITEA_DOCKER_NETWORK}; instala/prepara primero Stack0"
driver="$(docker network inspect -f '{{.Driver}}' "${GITEA_DOCKER_NETWORK}")"
[[ "${driver}" == "bridge" ]] || die "${GITEA_DOCKER_NETWORK} usa driver ${driver}, no bridge"
log "red de Stack0 verificada"

step "Token persistente del runner"
if [[ -s "${RUNNER_TOKEN_FILE}" ]]; then
  log "token existente preservado"
else
  umask 077
  if [[ -n "${GITEA_RUNNER_REGISTRATION_TOKEN:-}" && "${GITEA_RUNNER_REGISTRATION_TOKEN}" != PUT_YOUR_* ]]; then
    printf '%s\n' "${GITEA_RUNNER_REGISTRATION_TOKEN}" >"${RUNNER_TOKEN_FILE}"
    log "token legacy de .env adoptado en runtime"
  else
    openssl rand -hex 24 >"${RUNNER_TOKEN_FILE}"
    log "token generado una vez en runtime"
  fi
fi
[[ -s "${RUNNER_TOKEN_FILE}" ]] || die "no se pudo preparar ${RUNNER_TOKEN_FILE}"
chown 0:"${GITEA_GID}" "${RUNNER_TOKEN_FILE}"
chmod 0440 "${RUNNER_TOKEN_FILE}"

escape_sed_replacement() { printf '%s' "$1" | sed 's/[\\&|]/\\&/g'; }
render_file() {
  local source="$1" target="$2"; shift 2
  local tmp="${target}.tmp.$$"
  cp "${source}" "${tmp}"
  while [[ "$#" -gt 0 ]]; do
    local token="$1" value="$2" escaped; shift 2
    escaped="$(escape_sed_replacement "${value}")"
    sed -i "s|@@${token}@@|${escaped}|g" "${tmp}"
  done
  grep -q '@@[A-Za-z0-9_][A-Za-z0-9_]*@@' "${tmp}" && { rm -f "${tmp}"; die "placeholders sin resolver en ${source}"; }
  mv "${tmp}" "${target}"
}

step "Configuracion de Gitea"
[[ ! -L "${GITEA_SERVICE}/config" ]] || die "${GITEA_SERVICE}/config no puede ser symlink"
[[ ! -e "${GITEA_SERVICE}/config" || -d "${GITEA_SERVICE}/config" ]] || \
  die "${GITEA_SERVICE}/config existe pero no es un directorio"
install -d -m 0750 -o "${GITEA_UID}" -g "${GITEA_GID}" \
  "${GITEA_SERVICE}/config" "${GITEA_SERVICE}/config/conf"

render_file "${APP_SOURCE}" "${APP_TARGET}" \
  GITEA_DOMAIN "${GITEA_DOMAIN}" GITEA_ROOT_URL "${GITEA_ROOT_URL}" \
  GITEA_SSH_DOMAIN "${GITEA_SSH_DOMAIN}" GITEA_SSH_PORT "${GITEA_SSH_PORT}" \
  GITEA_INTERNAL_TOKEN "${GITEA_INTERNAL_TOKEN}" GITEA_JWT_SECRET "${GITEA_JWT_SECRET}"
chmod 0640 "${APP_TARGET}"

if [[ -L "${APP_DEFAULT_TARGET}" ]]; then
  [[ "$(readlink -- "${APP_DEFAULT_TARGET}")" == "../app.ini" ]] || \
    die "${APP_DEFAULT_TARGET} es un symlink inesperado"
elif [[ -e "${APP_DEFAULT_TARGET}" ]]; then
  die "${APP_DEFAULT_TARGET} existe y no es el alias gestionado esperado"
else
  ln -s -- ../app.ini "${APP_DEFAULT_TARGET}"
fi

chown -R "${GITEA_UID}:${GITEA_GID}" "${GITEA_SERVICE}/config" "${GITEA_SERVICE}/data"
log "config bind preservado; app.ini disponible tambien en custom/conf/app.ini"

step "Configuracion del runner"
rm -f "${RUNNER_SERVICE}/data/ca-certificates.crt" "${RUNNER_SERVICE}/data/certificates.txt"
render_file "${RUNNER_SOURCE}" "${RUNNER_TARGET}" GITEA_DOCKER_NETWORK "${GITEA_DOCKER_NETWORK}"
chmod 0640 "${RUNNER_TARGET}"
chown -R "${GITEA_UID}:${GITEA_GID}" "${RUNNER_SERVICE}/data"

step "Validacion de Docker Compose"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" config --quiet
log "compose valido"

{
  printf 'stack=%s\n' "${STACK_NAME}"
  printf 'prepared_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "${LOCK_FILE}"

step "Preparacion terminada"
log "lock creado: ${LOCK_FILE}"
log "runner token: runtime persistente, no requerido en .env"
log "ejecuta ./02-run.sh para migrar Gitea, asegurar el administrador y arrancar el stack"
