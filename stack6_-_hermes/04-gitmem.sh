#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

# =============================================================================
# Prepare/adopt Git-backed Hermes memory
# =============================================================================
# Contract:
#   - Stack6 .env already exists and is never modified here.
#   - Stack6 must already have been prepared successfully (.lock exists).
#   - Hermes must be stopped while the memory working tree is adopted/validated.
#   - service_-_hermes-memory/data keeps its directory identity.
#   - MEMORY.md and USER.md are the only files managed by the Git memory repo.
#   - Existing local memory is never silently overwritten.
#   - If local and remote both contain different non-empty content, fail closed.
#   - This script NEVER pulls, merges, rebases, commits, pushes or force-resets.
#   - Git credentials are external to this stack and are never stored in .env.
# =============================================================================

STACK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ENV_FILE="${STACK_DIR}/.env"
LOCK_FILE="${STACK_DIR}/.lock"

log()  { printf '  %s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "ejecutar como root"

for cmd in git docker install stat find realpath chown chmod sha256sum awk cmp mktemp cp mv rm; do
  command -v "${cmd}" >/dev/null 2>&1 || die "falta el comando requerido: ${cmd}"
done

[[ -f "${ENV_FILE}" ]] || die "falta ${ENV_FILE}"
[[ -f "${LOCK_FILE}" ]] || die "Stack6 no esta preparado: falta ${LOCK_FILE}; ejecutar primero 01-prepare.sh"

ENV_SHA256_BEFORE="$(sha256sum "${ENV_FILE}" | awk '{print $1}')"
LOCK_SHA256_BEFORE="$(sha256sum "${LOCK_FILE}" | awk '{print $1}')"

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

required=(
  BASE_PATH
  HERMES_SERVICE
  HERMES_MEMORY_SERVICE
  HERMES_CONTAINER
  HERMES_UID
  HERMES_GID
  GITMEM_REPOSITORY
  GITMEM_BRANCH
)
for key in "${required[@]}"; do
  [[ -n "${!key:-}" ]] || die "falta ${key} en ${ENV_FILE}"
done

[[ "${BASE_PATH}" == /* ]] || die "BASE_PATH debe ser una ruta absoluta"
BASE_PATH="${BASE_PATH%/}"
[[ -n "${BASE_PATH}" && "${BASE_PATH}" != "/" ]] || die "BASE_PATH no puede ser /"

[[ "${HERMES_SERVICE}" =~ ^service_-_[A-Za-z0-9._-]+$ ]] \
  || die "HERMES_SERVICE debe seguir el patron service_-_*"
[[ "${HERMES_MEMORY_SERVICE}" =~ ^service_-_[A-Za-z0-9._-]+$ ]] \
  || die "HERMES_MEMORY_SERVICE debe seguir el patron service_-_*"
[[ "${HERMES_MEMORY_SERVICE}" != "${HERMES_SERVICE}" ]] \
  || die "HERMES_MEMORY_SERVICE debe ser distinto de HERMES_SERVICE"
[[ "${GITMEM_BRANCH}" =~ ^[A-Za-z0-9._/-]+$ ]] \
  || die "GITMEM_BRANCH contiene caracteres no admitidos"

if [[ "${GITMEM_REPOSITORY}" =~ ^https?://[^/]*@ ]]; then
  die "GITMEM_REPOSITORY no debe incluir credenciales embebidas; usa Git credential/SSH externo"
fi

BASE_REAL="$(realpath -m -- "${BASE_PATH}")"
HERMES_ROOT="$(realpath -m -- "${BASE_REAL}/${HERMES_SERVICE}")"
MEMORY_ROOT="$(realpath -m -- "${BASE_REAL}/${HERMES_MEMORY_SERVICE}")"
MEMORY_DATA="${MEMORY_ROOT}/data"
LEGACY_MEMORY="${HERMES_ROOT}/data/memories"

case "${MEMORY_ROOT}" in
  "${BASE_REAL}"/service_-_*) ;;
  *) die "ruta de memoria fuera del arbol service_-_* esperado: ${MEMORY_ROOT}" ;;
esac
[[ "${MEMORY_ROOT}" != "/" && "${MEMORY_ROOT}" != "${BASE_REAL}" ]] \
  || die "ruta de memoria insegura: ${MEMORY_ROOT}"

step "Estado de Hermes"
if docker inspect "${HERMES_CONTAINER}" >/dev/null 2>&1; then
  running="$(docker inspect -f '{{.State.Running}}' "${HERMES_CONTAINER}")"
  [[ "${running}" != "true" ]] \
    || die "el contenedor ${HERMES_CONTAINER} sigue corriendo; detener solo Hermes antes de preparar Git memory"
  log "${HERMES_CONTAINER}: detenido"
else
  log "${HERMES_CONTAINER}: no creado"
fi

step "Directorio persistente de memoria"
[[ ! -L "${MEMORY_ROOT}" ]] || die "${MEMORY_ROOT} no puede ser symlink"
[[ ! -e "${MEMORY_ROOT}" || -d "${MEMORY_ROOT}" ]] || die "${MEMORY_ROOT} no es un directorio"
install -d -m 0750 -o "${HERMES_UID}" -g "${HERMES_GID}" "${MEMORY_ROOT}"

[[ ! -L "${MEMORY_DATA}" ]] || die "${MEMORY_DATA} no puede ser symlink"
[[ ! -e "${MEMORY_DATA}" || -d "${MEMORY_DATA}" ]] || die "${MEMORY_DATA} existe pero no es un directorio"
install -d -m 0750 -o "${HERMES_UID}" -g "${HERMES_GID}" "${MEMORY_DATA}"

for file in MEMORY.md USER.md; do
  path="${MEMORY_DATA}/${file}"
  [[ ! -L "${path}" ]] || die "${path} no puede ser symlink"
  [[ ! -e "${path}" || -f "${path}" ]] || die "${path} existe pero no es fichero normal"
  if [[ ! -e "${path}" ]]; then
    install -m 0640 -o "${HERMES_UID}" -g "${HERMES_GID}" /dev/null "${path}"
    log "creado fichero local vacio: ${file}"
  fi
done

step "Working tree Git"
if [[ -d "${MEMORY_DATA}/.git" && ! -L "${MEMORY_DATA}/.git" ]]; then
  log "working tree existente conservado"
else
  [[ ! -e "${MEMORY_DATA}/.git" ]] || die "${MEMORY_DATA}/.git existe pero no es un directorio normal"

  unexpected="$(find "${MEMORY_DATA}" -mindepth 1 -maxdepth 1 \
    ! -name MEMORY.md ! -name USER.md -printf '%f\n' | LC_ALL=C sort)"
  [[ -z "${unexpected}" ]] || die "memoria local contiene entradas no gestionadas antes de adoptar Git: ${unexpected}"

  TMP_CLONE="$(mktemp -d "${MEMORY_ROOT}/.gitmem-adopt.XXXXXX")"
  cleanup_tmp() {
    if [[ -n "${TMP_CLONE:-}" && -d "${TMP_CLONE}" ]]; then
      rm -rf -- "${TMP_CLONE}"
    fi
  }
  trap cleanup_tmp EXIT

  log "clonando temporalmente ${GITMEM_REPOSITORY} (${GITMEM_BRANCH}) para validar adopcion"
  git clone --single-branch --branch "${GITMEM_BRANCH}" -- "${GITMEM_REPOSITORY}" "${TMP_CLONE}"

  TMP_GIT=(git -c "safe.directory=${TMP_CLONE}" -C "${TMP_CLONE}")
  tracked="$("${TMP_GIT[@]}" ls-files | LC_ALL=C sort)"
  expected=$'MEMORY.md\nUSER.md'
  [[ "${tracked}" == "${expected}" ]] \
    || die "el repositorio Git memory debe contener exactamente MEMORY.md y USER.md como ficheros versionados"

  for file in MEMORY.md USER.md; do
    local_file="${MEMORY_DATA}/${file}"
    remote_file="${TMP_CLONE}/${file}"
    [[ -f "${remote_file}" && ! -L "${remote_file}" ]] \
      || die "el repositorio debe contener ${file} como fichero normal"

    if cmp -s "${local_file}" "${remote_file}"; then
      log "${file}: local y remoto coinciden"
    elif [[ ! -s "${local_file}" && -s "${remote_file}" ]]; then
      cp -- "${remote_file}" "${local_file}"
      log "${file}: local vacio; adoptado contenido remoto"
    elif [[ -s "${local_file}" && ! -s "${remote_file}" ]]; then
      log "${file}: remoto vacio; contenido local preservado como cambio pendiente"
    else
      die "${file}: local y remoto contienen contenido distinto; resolver manualmente antes de habilitar Git memory"
    fi
  done

  mv -- "${TMP_CLONE}/.git" "${MEMORY_DATA}/.git"
  log "metadata Git adoptada sin sustituir el directorio persistente de memoria"

  cleanup_tmp
  trap - EXIT
fi

GIT=(git -c "safe.directory=${MEMORY_DATA}" -C "${MEMORY_DATA}")

origin="$("${GIT[@]}" remote get-url origin 2>/dev/null || true)"
[[ -n "${origin}" ]] || die "el working tree no tiene remote origin"
[[ "${origin}" == "${GITMEM_REPOSITORY}" ]] \
  || die "origin inesperado: '${origin}' (esperado '${GITMEM_REPOSITORY}')"

branch="$("${GIT[@]}" branch --show-current)"
[[ "${branch}" == "${GITMEM_BRANCH}" ]] \
  || die "branch activa inesperada: '${branch}' (esperada '${GITMEM_BRANCH}')"

tracked="$("${GIT[@]}" ls-files | LC_ALL=C sort)"
expected=$'MEMORY.md\nUSER.md'
[[ "${tracked}" == "${expected}" ]] \
  || die "Git memory debe gestionar exactamente MEMORY.md y USER.md"

for file in MEMORY.md USER.md; do
  path="${MEMORY_DATA}/${file}"
  [[ -f "${path}" && ! -L "${path}" ]] \
    || die "el repositorio debe contener ${file} como fichero normal"
done

step "Memoria legacy"
for file in MEMORY.md USER.md; do
  legacy="${LEGACY_MEMORY}/${file}"
  current="${MEMORY_DATA}/${file}"
  if [[ -f "${legacy}" && -s "${legacy}" ]]; then
    cmp -s "${legacy}" "${current}" \
      || die "${legacy} contiene memoria distinta. Migra ese contenido deliberadamente y vuelve a ejecutar 04-gitmem.sh"
    log "${file}: legacy coincide con memoria activa"
  else
    log "${file}: sin memoria legacy no vacia"
  fi
done

chown -R "${HERMES_UID}:${HERMES_GID}" "${MEMORY_DATA}"
chmod 0750 "${MEMORY_DATA}"
chmod 0640 "${MEMORY_DATA}/MEMORY.md" "${MEMORY_DATA}/USER.md"

step "Auditoria"
[[ -d "${MEMORY_DATA}/.git" && ! -L "${MEMORY_DATA}/.git" ]] \
  || die ".git ausente o invalido"
[[ "$(stat -c '%u:%g:%a' "${MEMORY_DATA}")" == "${HERMES_UID}:${HERMES_GID}:750" ]] \
  || die "propietario/permisos inesperados en ${MEMORY_DATA}"
for file in MEMORY.md USER.md; do
  [[ "$(stat -c '%u:%g:%a' "${MEMORY_DATA}/${file}")" == "${HERMES_UID}:${HERMES_GID}:640" ]] \
    || die "propietario/permisos inesperados en ${MEMORY_DATA}/${file}"
done

changed_paths="$({
  "${GIT[@]}" diff --name-only
  "${GIT[@]}" diff --cached --name-only
  "${GIT[@]}" ls-files --others --exclude-standard
} | LC_ALL=C sort -u | awk 'NF')"
if [[ -n "${changed_paths}" ]]; then
  while IFS= read -r path; do
    case "${path}" in
      MEMORY.md|USER.md) ;;
      *) die "cambio no autorizado tras adopcion: ${path}" ;;
    esac
  done <<< "${changed_paths}"
fi

ENV_SHA256_AFTER="$(sha256sum "${ENV_FILE}" | awk '{print $1}')"
LOCK_SHA256_AFTER="$(sha256sum "${LOCK_FILE}" | awk '{print $1}')"
[[ "${ENV_SHA256_BEFORE}" == "${ENV_SHA256_AFTER}" ]] \
  || die ".env ha cambiado durante 04-gitmem.sh"
[[ "${LOCK_SHA256_BEFORE}" == "${LOCK_SHA256_AFTER}" ]] \
  || die ".lock ha cambiado durante 04-gitmem.sh"

log "working tree: ${MEMORY_DATA}"
log "origin: ${origin}"
log "branch: ${branch}"
log "MEMORY.md / USER.md: OK"
if [[ -n "${changed_paths}" ]]; then
  log "cambios locales de memoria preservados; el sidecar podra sincronizarlos de forma conservadora"
else
  log "working tree alineado con Git"
fi
log ".env y .lock inmutables: OK"

cat <<EOF

Git-backed memory preparada y auditada.

Este script NO ha ejecutado pull/merge/rebase/commit/push/reset.
La sincronizacion se habilita separadamente mediante el profile git-memory.
EOF
