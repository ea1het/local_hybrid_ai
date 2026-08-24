#!/usr/bin/env bash
# =============================================================================
# Prepare Stack6 - Hermes Agent + isolated SSH sandbox
# =============================================================================
# Contract:
#   - .env already exists and is complete.
#   - this script NEVER creates, edits or rewrites .env.
#   - if .lock exists, exit immediately: no validation, no cleanup, no changes.
#   - cleanup/reset belongs to 02-cleanup.sh.
#   - data/, logs/, workspace and persistent binaries are never deleted here.
#   - managed config is reconciled from the stack and strictly audited.
#   - HERMES_MODEL is rendered at prepare time into the deployed config.yaml.
#   - .lock is created only after the complete filesystem audit succeeds.
# =============================================================================

set -euo pipefail

STACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCK_FILE="${STACK_DIR}/.lock"
ENV_FILE="${STACK_DIR}/.env"

log()  { printf '  %s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
warn() { printf '  AVISO: %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# -----------------------------------------------------------------------------
# LOCK: this is deliberately the first operational check.
# -----------------------------------------------------------------------------
if [[ -f "${LOCK_FILE}" ]]; then
  printf 'LOCK: %s existe. No se valida ni se modifica nada.\n' "${LOCK_FILE}"
  exit 0
fi

# -----------------------------------------------------------------------------
# Host prerequisites
# -----------------------------------------------------------------------------
[[ "$(id -u)" -eq 0 ]] || die "ejecutar como root"

for cmd in docker ssh-keygen install grep chmod chown stat find sort cmp sha256sum awk rm mktemp; do
  command -v "${cmd}" >/dev/null 2>&1 || die "falta el comando requerido: ${cmd}"
done

docker compose version >/dev/null 2>&1 \
  || die "se requiere Docker Compose v2 ('docker compose')"

[[ -f "${ENV_FILE}" ]] || die "falta ${ENV_FILE}; el script no lo crea"

ENV_SHA256_BEFORE="$(sha256sum "${ENV_FILE}" | awk '{print $1}')"

# -----------------------------------------------------------------------------
# .env contract validation - READ ONLY
# -----------------------------------------------------------------------------
step "Validacion de .env (solo lectura)"

ALL_KEYS=(
  BASE_PATH NETWORK_NAME TZ
  HERMES_SERVICE SANDBOX_SERVICE
  HERMES_CONTAINER SANDBOX_CONTAINER
  HERMES_IMAGE SANDBOX_IMAGE
  HERMES_UID HERMES_GID
  HERMES_MODEL LITELLM_BASE_URL LITELLM_API_KEY
  HERMES_DASHBOARD HERMES_DASHBOARD_HOST
  API_SERVER_ENABLED API_SERVER_HOST API_SERVER_PORT API_SERVER_KEY
  API_SERVER_MODEL_NAME API_SERVER_CORS_ORIGINS
  SEARXNG_URL FIRECRAWL_API_URL FIRECRAWL_API_KEY
  TERMINAL_SSH_HOST TERMINAL_SSH_USER TERMINAL_SSH_PORT TERMINAL_SSH_KEY
  TERMINAL_SSH_PERSISTENT TERMINAL_TIMEOUT
  SANDBOX_UID SANDBOX_GID SANDBOX_CPU SANDBOX_MEMORY SANDBOX_PIDS
  SANDBOX_SHM_SIZE
)

for key in "${ALL_KEYS[@]}"; do
  grep -qE "^${key}=" "${ENV_FILE}" || die "falta la variable ${key} en .env"
done

# shellcheck disable=SC1090
set -a
source "${ENV_FILE}"
set +a

REQUIRED_NONEMPTY=(
  BASE_PATH NETWORK_NAME TZ
  HERMES_SERVICE SANDBOX_SERVICE
  HERMES_CONTAINER SANDBOX_CONTAINER
  HERMES_IMAGE SANDBOX_IMAGE
  HERMES_UID HERMES_GID
  HERMES_MODEL LITELLM_BASE_URL LITELLM_API_KEY
  HERMES_DASHBOARD HERMES_DASHBOARD_HOST
  API_SERVER_ENABLED API_SERVER_HOST API_SERVER_PORT API_SERVER_KEY
  API_SERVER_MODEL_NAME
  SEARXNG_URL FIRECRAWL_API_URL
  TERMINAL_SSH_HOST TERMINAL_SSH_USER TERMINAL_SSH_PORT TERMINAL_SSH_KEY
  TERMINAL_SSH_PERSISTENT TERMINAL_TIMEOUT
  SANDBOX_UID SANDBOX_GID SANDBOX_CPU SANDBOX_MEMORY SANDBOX_PIDS
  SANDBOX_SHM_SIZE
)

for key in "${REQUIRED_NONEMPTY[@]}"; do
  value="${!key:-}"
  [[ -n "${value}" ]] || die "${key} esta vacia en .env"
  [[ "${value}" != CHANGE_ME* ]] || die "${key} sigue sin definir: ${value}"
done

[[ ${#API_SERVER_KEY} -ge 8 ]] || die "API_SERVER_KEY debe tener al menos 8 caracteres"
[[ "${BASE_PATH}" == /* ]] || die "BASE_PATH debe ser una ruta absoluta"

BASE_PATH="${BASE_PATH%/}"
[[ -n "${BASE_PATH}" && "${BASE_PATH}" != "/" ]] || die "BASE_PATH no puede ser /"

[[ "${HERMES_SERVICE}" =~ ^service_-_[A-Za-z0-9._-]+$ ]] \
  || die "HERMES_SERVICE debe seguir el patron service_-_*"
[[ "${SANDBOX_SERVICE}" =~ ^service_-_[A-Za-z0-9._-]+$ ]] \
  || die "SANDBOX_SERVICE debe seguir el patron service_-_*"
[[ "${HERMES_SERVICE}" != "${SANDBOX_SERVICE}" ]] \
  || die "HERMES_SERVICE y SANDBOX_SERVICE no pueden ser iguales"

HERMES_ROOT="${BASE_PATH}/${HERMES_SERVICE}"
SANDBOX_ROOT="${BASE_PATH}/${SANDBOX_SERVICE}"

HERMES_CONFIG="${HERMES_ROOT}/config"
HERMES_DATA="${HERMES_ROOT}/data"
HERMES_LOGS="${HERMES_ROOT}/logs"

SANDBOX_CONFIG="${SANDBOX_ROOT}/config"
SANDBOX_DATA="${SANDBOX_ROOT}/data"
SANDBOX_LOGS="${SANDBOX_ROOT}/logs"

log ".env completo; no se ha modificado"

# -----------------------------------------------------------------------------
# Source files
# -----------------------------------------------------------------------------
step "Ficheros fuente del stack"

HERMES_CONFIG_SRC="${STACK_DIR}/config/hermes/config.yaml"
SANDBOX_DOCKERFILE_SRC="${STACK_DIR}/config/sandbox/Dockerfile"
SANDBOX_ENTRYPOINT_SRC="${STACK_DIR}/config/sandbox/entrypoint.sh"

[[ -s "${HERMES_CONFIG_SRC}" ]] || die "falta o esta vacio ${HERMES_CONFIG_SRC}"
[[ -s "${SANDBOX_DOCKERFILE_SRC}" ]] || die "falta o esta vacio ${SANDBOX_DOCKERFILE_SRC}"
[[ -s "${SANDBOX_ENTRYPOINT_SRC}" ]] || die "falta o esta vacio ${SANDBOX_ENTRYPOINT_SRC}"

# HERMES_MODEL is the single source of truth for model selection. The source
# config intentionally contains ${HERMES_MODEL}; prepare renders ONLY that
# variable into the deployed config. Other ${...} expressions remain untouched.
grep -qF '${HERMES_MODEL}' "${HERMES_CONFIG_SRC}" \
  || die "config/hermes/config.yaml debe contener \${HERMES_MODEL}"

[[ "${HERMES_MODEL}" =~ ^[A-Za-z0-9._:/+@-]+$ ]] \
  || die "HERMES_MODEL contiene caracteres no admitidos para render seguro: ${HERMES_MODEL}"

# Every actual model reference in the managed source must use HERMES_MODEL.
# This prevents a future model change from leaving MoA/auxiliary/compression
# pinned to an old literal model name.
SOURCE_MAIN_MODEL="$(
  awk '
    /^model:[[:space:]]*$/ { in_model=1; next }
    in_model && /^[^[:space:]]/ { exit }
    in_model && /^[[:space:]]+default:[[:space:]]*/ {
      sub(/^[[:space:]]+default:[[:space:]]*/, "")
      print
      exit
    }
  ' "${HERMES_CONFIG_SRC}"
)"

[[ "${SOURCE_MAIN_MODEL}" == '${HERMES_MODEL}' ]] \
  || die "model.default en config/hermes/config.yaml debe ser \${HERMES_MODEL}"

while IFS= read -r MODEL_REF; do
  [[ "${MODEL_REF}" == '${HERMES_MODEL}' ]] \
    || die "referencia de modelo hardcodeada en config/hermes/config.yaml: ${MODEL_REF}"
done < <(
  awk '
    /^[[:space:]]+model:[[:space:]]+/ {
      sub(/^[[:space:]]+model:[[:space:]]*/, "")
      print
    }
  ' "${HERMES_CONFIG_SRC}"
)

SOURCE_SUMMARY_MODEL="$(
  awk '
    /^[[:space:]]*summary_model:[[:space:]]*/ {
      sub(/^[[:space:]]*summary_model:[[:space:]]*/, "")
      print
      exit
    }
  ' "${HERMES_CONFIG_SRC}"
)"

if [[ -n "${SOURCE_SUMMARY_MODEL}" ]]; then
  [[ "${SOURCE_SUMMARY_MODEL}" == '${HERMES_MODEL}' ]] \
    || die "compression.summary_model debe ser \${HERMES_MODEL}"
fi

# The runtime entrypoint must never prepare ownership/authorized_keys.
if grep -qE '(^|[[:space:]])(install|chown|chmod)([[:space:]]|$)|hermes_authorized_key|AUTHORIZED_SOURCE' \
     "${SANDBOX_ENTRYPOINT_SRC}"; then
  die "entrypoint.sh contiene logica de preparacion antigua; no se instala"
fi

log "fuentes presentes y coherentes"

# -----------------------------------------------------------------------------
# Docker network
# -----------------------------------------------------------------------------
step "Red Docker ${NETWORK_NAME}"

if docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1; then
  driver="$(docker network inspect -f '{{.Driver}}' "${NETWORK_NAME}")"
  [[ "${driver}" == "bridge" ]] \
    || die "la red ${NETWORK_NAME} existe pero usa driver '${driver}', no bridge"
  log "existe y es bridge"
else
  docker network create --driver bridge "${NETWORK_NAME}" >/dev/null
  log "creada como bridge"
fi

# -----------------------------------------------------------------------------
# Containers must be stopped. Cleanup is handled by 02-cleanup.sh.
# -----------------------------------------------------------------------------
step "Estado de Hermes"

for container in "${HERMES_CONTAINER}" "${SANDBOX_CONTAINER}"; do
  if docker inspect "${container}" >/dev/null 2>&1; then
    running="$(docker inspect -f '{{.State.Running}}' "${container}")"
    [[ "${running}" != "true" ]] \
      || die "el contenedor '${container}' sigue corriendo; ejecutar docker compose stop"
    log "${container}: detenido"
  else
    log "${container}: no creado"
  fi
done

# -----------------------------------------------------------------------------
# Persistent target filesystem
# -----------------------------------------------------------------------------
step "Creacion/verificacion del arbol objetivo"

install -d -m 0750 -o "${HERMES_UID}" -g "${HERMES_GID}" \
  "${HERMES_ROOT}" \
  "${HERMES_CONFIG}" \
  "${HERMES_DATA}" \
  "${HERMES_LOGS}"
install -d -m 0700 -o "${HERMES_UID}" -g "${HERMES_GID}" \
  "${HERMES_CONFIG}/ssh"

install -d -m 0750 -o 0 -g 0 \
  "${SANDBOX_ROOT}" \
  "${SANDBOX_CONFIG}" \
  "${SANDBOX_CONFIG}/ssh-host" \
  "${SANDBOX_DATA}"
install -d -m 0750 -o "${SANDBOX_UID}" -g "${SANDBOX_GID}" \
  "${SANDBOX_DATA}/home" \
  "${SANDBOX_DATA}/workspace" \
  "${SANDBOX_LOGS}"
install -d -m 0700 -o "${SANDBOX_UID}" -g "${SANDBOX_GID}" \
  "${SANDBOX_DATA}/home/.ssh"

log "${HERMES_ROOT}/{config,data,logs}"
log "${SANDBOX_ROOT}/{config,data,logs}"
log "data/, logs/, workspace y data/bin se preservan"

# -----------------------------------------------------------------------------
# Shadow configuration
# -----------------------------------------------------------------------------
step "Shadow configuration"

SHADOW_FOUND=0

for path in \
  "${HERMES_DATA}/.hermes" \
  "${HERMES_DATA}/config.yaml"
do
  if [[ -e "${path}" || -L "${path}" ]]; then
    warn "configuracion shadow detectada: ${path}"
    SHADOW_FOUND=1
  fi
done

shopt -s nullglob
for path in "${HERMES_DATA}"/.env*; do
  warn "dotenv shadow detectado: ${path}"
  SHADOW_FOUND=1
done
shopt -u nullglob

(( SHADOW_FOUND == 0 )) \
  || die "hay configuracion runtime que puede pisar el despliegue; ejecutar 02-cleanup.sh"

log "sin data/.env*, data/.hermes ni data/config.yaml"

# -----------------------------------------------------------------------------
# Managed configuration: stack -> service
# -----------------------------------------------------------------------------
step "Configuracion gestionada"

RENDERED_CONFIG="$(mktemp)"
trap 'rm -f "${RENDERED_CONFIG:-}"' EXIT

awk -v model="${HERMES_MODEL}" '
  {
    gsub(/\$\{HERMES_MODEL\}/, model)
    print
  }
' "${HERMES_CONFIG_SRC}" > "${RENDERED_CONFIG}"

[[ -s "${RENDERED_CONFIG}" ]] || die "config.yaml renderizado esta vacio"

if grep -qF '${HERMES_MODEL}' "${RENDERED_CONFIG}"; then
  die "config.yaml renderizado conserva \${HERMES_MODEL}; se aborta"
fi

DEPLOYED_MODEL="$(
  awk '
    /^model:[[:space:]]*$/ { in_model=1; next }
    in_model && /^[^[:space:]]/ { exit }
    in_model && /^[[:space:]]+default:[[:space:]]*/ {
      sub(/^[[:space:]]+default:[[:space:]]*/, "")
      print
      exit
    }
  ' "${RENDERED_CONFIG}"
)"

[[ "${DEPLOYED_MODEL}" == "${HERMES_MODEL}" ]] \
  || die "model.default renderizado '${DEPLOYED_MODEL}' no coincide con HERMES_MODEL='${HERMES_MODEL}'"

install -m 0640 -o "${HERMES_UID}" -g "${HERMES_GID}" \
  "${RENDERED_CONFIG}" "${HERMES_CONFIG}/config.yaml"
install -m 0644 -o 0 -g 0 \
  "${SANDBOX_DOCKERFILE_SRC}" "${SANDBOX_CONFIG}/Dockerfile"
install -m 0755 -o 0 -g 0 \
  "${SANDBOX_ENTRYPOINT_SRC}" "${SANDBOX_CONFIG}/entrypoint.sh"

log "configuracion sincronizada; HERMES_MODEL renderizado como ${HERMES_MODEL}"

# -----------------------------------------------------------------------------
# SSH identities
# -----------------------------------------------------------------------------
step "Claves SSH"

SSH_PRIVATE="${HERMES_CONFIG}/ssh/hermes_executor_ed25519"
SSH_PUBLIC="${SSH_PRIVATE}.pub"
AUTHORIZED_KEYS="${SANDBOX_DATA}/home/.ssh/authorized_keys"
HOST_PRIVATE="${SANDBOX_CONFIG}/ssh-host/ssh_host_ed25519_key"
HOST_PUBLIC="${HOST_PRIVATE}.pub"

ensure_keypair() {
  local private="$1" public="$2" comment="$3" uid="$4" gid="$5"
  local derived actual

  if [[ -e "${private}" || -e "${public}" ]]; then
    [[ -s "${private}" && -s "${public}" ]] \
      || die "pareja SSH incompleta: ${private} / ${public}"

    derived="$(ssh-keygen -y -f "${private}" | awk '{print $1" "$2}')"
    actual="$(awk '{print $1" "$2}' "${public}")"

    [[ "${derived}" == "${actual}" ]] \
      || die "pareja SSH incoherente: ${private} / ${public}"

    log "clave existente conservada: ${private}"
  else
    umask 077
    ssh-keygen -q -t ed25519 -N "" -C "${comment}" -f "${private}"
    log "clave creada: ${private}"
  fi

  chown "${uid}:${gid}" "${private}" "${public}"
  chmod 0600 "${private}"
  chmod 0644 "${public}"
}

ensure_keypair \
  "${SSH_PRIVATE}" "${SSH_PUBLIC}" \
  "hermes-sandbox" "${HERMES_UID}" "${HERMES_GID}"

ensure_keypair \
  "${HOST_PRIVATE}" "${HOST_PUBLIC}" \
  "hermes-sandbox-host" 0 0

install -m 0600 -o "${SANDBOX_UID}" -g "${SANDBOX_GID}" \
  "${SSH_PUBLIC}" "${AUTHORIZED_KEYS}"

log "Hermes -> sandbox: ${AUTHORIZED_KEYS}"
log "host key sandbox: ${HOST_PRIVATE}"

# -----------------------------------------------------------------------------
# Dependencies already running on redlocal
# -----------------------------------------------------------------------------
step "Dependencias existentes"

for container in litellm searxng firecrawl-api; do
  docker inspect "${container}" >/dev/null 2>&1 \
    || die "no existe el contenedor requerido '${container}'"

  running="$(docker inspect -f '{{.State.Running}}' "${container}")"
  [[ "${running}" == "true" ]] || die "el contenedor '${container}' no esta corriendo"

  attached="$(docker inspect -f "{{if index .NetworkSettings.Networks \"${NETWORK_NAME}\"}}yes{{else}}no{{end}}" "${container}")"
  [[ "${attached}" == "yes" ]] \
    || die "el contenedor '${container}' no esta conectado a ${NETWORK_NAME}"

  log "${container}: running + ${NETWORK_NAME}"
done

# -----------------------------------------------------------------------------
# Docker Compose validation
# -----------------------------------------------------------------------------
step "Validacion Docker Compose"

cd "${STACK_DIR}"
docker compose config --quiet
log "docker compose config: OK"

# -----------------------------------------------------------------------------
# Final strict filesystem audit
# -----------------------------------------------------------------------------
step "Auditoria final del filesystem"

assert_dir() {
  local path="$1" uid="$2" gid="$3" mode="$4"
  [[ -d "${path}" && ! -L "${path}" ]] || die "directorio ausente o invalido: ${path}"
  [[ "$(stat -c '%u:%g:%a' "${path}")" == "${uid}:${gid}:${mode}" ]] \
    || die "permisos/propietario incorrectos en ${path}: $(stat -c '%u:%g:%a' "${path}") esperado ${uid}:${gid}:${mode}"
}

assert_file() {
  local path="$1" uid="$2" gid="$3" mode="$4"
  [[ -f "${path}" && ! -L "${path}" && -s "${path}" ]] || die "fichero ausente, vacio o invalido: ${path}"
  [[ "$(stat -c '%u:%g:%a' "${path}")" == "${uid}:${gid}:${mode}" ]] \
    || die "permisos/propietario incorrectos en ${path}: $(stat -c '%u:%g:%a' "${path}") esperado ${uid}:${gid}:${mode}"
}

assert_exact_tree() {
  local root="$1" expected="$2" actual
  actual="$(find "${root}" -mindepth 1 -printf '%P\n' | LC_ALL=C sort)"
  [[ "${actual}" == "${expected}" ]] || {
    printf 'ERROR: arbol inesperado bajo %s\n' "${root}" >&2
    printf '%s\n' '--- esperado ---' >&2
    printf '%s\n' "${expected}" >&2
    printf '%s\n' '--- real ---' >&2
    printf '%s\n' "${actual}" >&2
    exit 1
  }
}

assert_top_level() {
  local root="$1" expected="$2" actual
  actual="$(find "${root}" -mindepth 1 -maxdepth 1 -printf '%P\n' | LC_ALL=C sort)"
  [[ "${actual}" == "${expected}" ]] || {
    printf 'ERROR: top-level inesperado bajo %s\n' "${root}" >&2
    printf '%s\n' '--- esperado ---' >&2
    printf '%s\n' "${expected}" >&2
    printf '%s\n' '--- real ---' >&2
    printf '%s\n' "${actual}" >&2
    exit 1
  }
}

ROOT_EXPECTED="$(cat <<'TREE'
config
data
logs
TREE
)"

HERMES_CONFIG_EXPECTED="$(cat <<'TREE'
config.yaml
ssh
ssh/hermes_executor_ed25519
ssh/hermes_executor_ed25519.pub
TREE
)"

SANDBOX_CONFIG_EXPECTED="$(cat <<'TREE'
Dockerfile
entrypoint.sh
ssh-host
ssh-host/ssh_host_ed25519_key
ssh-host/ssh_host_ed25519_key.pub
TREE
)"

# Runtime state is allowed under data/, logs/ and workspace. Exact auditing is
# retained for namespaces completely managed by prepare.
assert_top_level "${HERMES_ROOT}" "${ROOT_EXPECTED}"
assert_top_level "${SANDBOX_ROOT}" "${ROOT_EXPECTED}"
assert_exact_tree "${HERMES_CONFIG}" "${HERMES_CONFIG_EXPECTED}"
assert_exact_tree "${SANDBOX_CONFIG}" "${SANDBOX_CONFIG_EXPECTED}"
log "arbol gestionado: OK"

assert_dir "${HERMES_ROOT}"                    "${HERMES_UID}"  "${HERMES_GID}" 750
assert_dir "${HERMES_CONFIG}"                  "${HERMES_UID}"  "${HERMES_GID}" 750
assert_dir "${HERMES_CONFIG}/ssh"              "${HERMES_UID}"  "${HERMES_GID}" 700
assert_dir "${HERMES_DATA}"                    "${HERMES_UID}"  "${HERMES_GID}" 750
assert_dir "${HERMES_LOGS}"                    "${HERMES_UID}"  "${HERMES_GID}" 750
assert_file "${HERMES_CONFIG}/config.yaml"      "${HERMES_UID}"  "${HERMES_GID}" 640
assert_file "${SSH_PRIVATE}"                    "${HERMES_UID}"  "${HERMES_GID}" 600
assert_file "${SSH_PUBLIC}"                     "${HERMES_UID}"  "${HERMES_GID}" 644

assert_dir "${SANDBOX_ROOT}"                   0 0 750
assert_dir "${SANDBOX_CONFIG}"                 0 0 750
assert_dir "${SANDBOX_CONFIG}/ssh-host"        0 0 750
assert_file "${SANDBOX_CONFIG}/Dockerfile"     0 0 644
assert_file "${SANDBOX_CONFIG}/entrypoint.sh"  0 0 755
assert_file "${HOST_PRIVATE}"                   0 0 600
assert_file "${HOST_PUBLIC}"                    0 0 644
assert_dir "${SANDBOX_DATA}"                   0 0 750
assert_dir "${SANDBOX_DATA}/home"              "${SANDBOX_UID}" "${SANDBOX_GID}" 750
assert_dir "${SANDBOX_DATA}/home/.ssh"         "${SANDBOX_UID}" "${SANDBOX_GID}" 700
assert_file "${AUTHORIZED_KEYS}"                "${SANDBOX_UID}" "${SANDBOX_GID}" 600
assert_dir "${SANDBOX_DATA}/workspace"         "${SANDBOX_UID}" "${SANDBOX_GID}" 750
assert_dir "${SANDBOX_LOGS}"                   "${SANDBOX_UID}" "${SANDBOX_GID}" 750
log "propietarios/permisos: OK"

cmp -s "${RENDERED_CONFIG}" "${HERMES_CONFIG}/config.yaml" \
  || die "config.yaml desplegado no coincide con el render esperado"
cmp -s "${SANDBOX_DOCKERFILE_SRC}" "${SANDBOX_CONFIG}/Dockerfile" \
  || die "Dockerfile desplegado no coincide con la fuente"
cmp -s "${SANDBOX_ENTRYPOINT_SRC}" "${SANDBOX_CONFIG}/entrypoint.sh" \
  || die "entrypoint.sh desplegado no coincide con la fuente"
cmp -s "${SSH_PUBLIC}" "${AUTHORIZED_KEYS}" \
  || die "authorized_keys no coincide con la clave publica de Hermes"
log "ficheros gestionados: OK"

executor_derived="$(ssh-keygen -y -f "${SSH_PRIVATE}" | awk '{print $1" "$2}')"
executor_public="$(awk '{print $1" "$2}' "${SSH_PUBLIC}")"
[[ "${executor_derived}" == "${executor_public}" ]] \
  || die "la pareja SSH Hermes -> sandbox no es coherente"

host_derived="$(ssh-keygen -y -f "${HOST_PRIVATE}" | awk '{print $1" "$2}')"
host_public="$(awk '{print $1" "$2}' "${HOST_PUBLIC}")"
[[ "${host_derived}" == "${host_public}" ]] \
  || die "la pareja de host keys del sandbox no es coherente"
log "claves SSH: OK"

for path in \
  "${HERMES_DATA}/.hermes" \
  "${HERMES_DATA}/config.yaml"
do
  [[ ! -e "${path}" && ! -L "${path}" ]] \
    || die "configuracion shadow detectada durante auditoria: ${path}"
done

shopt -s nullglob
SHADOW_ENV=( "${HERMES_DATA}"/.env* )
shopt -u nullglob

(( ${#SHADOW_ENV[@]} == 0 )) \
  || die "dotenv shadow detectado durante auditoria: ${SHADOW_ENV[*]}"

if grep -qF '${HERMES_MODEL}' "${HERMES_CONFIG}/config.yaml"; then
  die "config.yaml desplegado contiene \${HERMES_MODEL}"
fi

AUDIT_MODEL="$(
  awk '
    /^model:[[:space:]]*$/ { in_model=1; next }
    in_model && /^[^[:space:]]/ { exit }
    in_model && /^[[:space:]]+default:[[:space:]]*/ {
      sub(/^[[:space:]]+default:[[:space:]]*/, "")
      print
      exit
    }
  ' "${HERMES_CONFIG}/config.yaml"
)"

[[ "${AUDIT_MODEL}" == "${HERMES_MODEL}" ]] \
  || die "model.default desplegado '${AUDIT_MODEL}' no coincide con HERMES_MODEL='${HERMES_MODEL}'"

log "modelo renderizado / shadow config: OK"

ENV_SHA256_AFTER="$(sha256sum "${ENV_FILE}" | awk '{print $1}')"
[[ "${ENV_SHA256_BEFORE}" == "${ENV_SHA256_AFTER}" ]] \
  || die ".env ha cambiado durante la preparacion; se aborta"
log ".env inmutable: OK"

# -----------------------------------------------------------------------------
# Lock only after the complete audit succeeds.
# -----------------------------------------------------------------------------
step "Lock"

install -m 0600 -o 0 -g 0 /dev/null "${LOCK_FILE}"
log "creado ${LOCK_FILE}"

cat <<EOF2

Stack preparado y auditado. No se ha arrancado ningun contenedor.

Siguiente paso:

  cd ${STACK_DIR}
  docker compose up -d --build
  docker compose ps

La salida correcta del prepare incluye:

  arbol gestionado: OK
  propietarios/permisos: OK
  ficheros gestionados: OK
  claves SSH: OK
  modelo renderizado / shadow config: OK
  .env inmutable: OK

IMPORTANTE:
  - eliminar .lock permite volver a ejecutar el prepare de forma deliberada.
  - 01-prepare.sh no borra data/, logs/, workspace ni data/bin.
  - la limpieza/reset/factory-reset corresponde a 02-cleanup.sh.
  - .env no se modifica nunca.
EOF2
