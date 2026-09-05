#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

# =============================================================================
# Prepare Git-backed Hermes memory
# =============================================================================
# Contract:
#   - Stack6 .env already exists and is never modified here.
#   - Stack6 must already have been prepared successfully (.lock exists).
#   - Hermes must be stopped while the memory mount is prepared/validated.
#   - service_-_hermes-memory/data is the real Git working tree.
#   - MEMORY.md and USER.md must already exist in the configured repository.
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

for cmd in git docker install stat find realpath chown chmod sha256sum awk cmp rmdir; do
  command -v "${cmd}" >/dev/null 2>&1 || die "falta el comando requerido: ${cmd}"
done

[[ -f "${ENV_FILE}" ]] || die "falta ${ENV_FILE}"
[[ -f "${LOCK_FILE}" ]] || die "Stack6 no esta preparado: falta ${LOCK_FILE}; ejecutar primero 01-prepare.sh"

ENV_SHA256_BEFORE="$(sha256sum "${ENV_FILE}" | awk '{print $1}')"

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

# Refuse obvious embedded HTTP(S) credentials. SSH URLs such as git@host:repo.git
# remain valid and obtain credentials from the host's Git/SSH configuration.
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
    || die "el contenedor ${HERMES_CONTAINER} sigue corriendo; detener Stack6 antes de preparar la memoria"
  log "${HERMES_CONTAINER}: detenido"
else
  log "${HERMES_CONTAINER}: no creado"
fi

step "Working tree de memoria"
install -d -m 0750 -o "${HERMES_UID}" -g "${HERMES_GID}" "${MEMORY_ROOT}"

if [[ ! -e "${MEMORY_DATA}" ]]; then
  log "clonando ${GITMEM_REPOSITORY} (${GITMEM_BRANCH}) -> ${MEMORY_DATA}"
  git clone --single-branch --branch "${GITMEM_BRANCH}" -- "${GITMEM_REPOSITORY}" "${MEMORY_DATA}"
elif [[ ! -d "${MEMORY_DATA}" ]]; then
  die "${MEMORY_DATA} existe pero no es un directorio"
elif [[ ! -d "${MEMORY_DATA}/.git" ]]; then
  if find "${MEMORY_DATA}" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
    die "${MEMORY_DATA} contiene datos pero no es un working tree Git; no se sobrescribe"
  fi
  rmdir "${MEMORY_DATA}"
  log "clonando ${GITMEM_REPOSITORY} (${GITMEM_BRANCH}) -> ${MEMORY_DATA}"
  git clone --single-branch --branch "${GITMEM_BRANCH}" -- "${GITMEM_REPOSITORY}" "${MEMORY_DATA}"
else
  log "working tree existente conservado"
fi

GIT=(git -c "safe.directory=${MEMORY_DATA}" -C "${MEMORY_DATA}")

origin="$("${GIT[@]}" remote get-url origin 2>/dev/null || true)"
[[ -n "${origin}" ]] || die "el working tree no tiene remote origin"
[[ "${origin}" == "${GITMEM_REPOSITORY}" ]] \
  || die "origin inesperado: '${origin}' (esperado '${GITMEM_REPOSITORY}')"

branch="$("${GIT[@]}" branch --show-current)"
[[ "${branch}" == "${GITMEM_BRANCH}" ]] \
  || die "branch activa inesperada: '${branch}' (esperada '${GITMEM_BRANCH}')"

# Do not require a clean tree: Hermes is expected to modify MEMORY.md / USER.md
# between future scheduler runs. Setup only validates structure and identity.
for file in MEMORY.md USER.md; do
  path="${MEMORY_DATA}/${file}"
  [[ -f "${path}" && ! -L "${path}" ]] \
    || die "el repositorio debe contener ${file} como fichero normal"
done

# Migration guard: before the new bind mount masks the old runtime memories,
# refuse startup if an existing non-empty legacy memory differs from Git.
# This makes the operator migrate/commit the current memory deliberately rather
# than silently losing sight of it behind the new mount.
step "Memoria legacy"
for file in MEMORY.md USER.md; do
  legacy="${LEGACY_MEMORY}/${file}"
  current="${MEMORY_DATA}/${file}"
  if [[ -f "${legacy}" && -s "${legacy}" ]]; then
    cmp -s "${legacy}" "${current}" \
      || die "${legacy} contiene memoria distinta de Git. Migra ese contenido al repositorio y vuelve a ejecutar 04-gitmem.sh"
    log "${file}: legacy coincide con Git"
  else
    log "${file}: sin memoria legacy no vacia"
  fi
done

# Hermes needs write access to its memory files and lock files. Keep the entire
# tiny working tree under the Hermes runtime UID/GID so Git-based maintenance
# can later run in a scheduler container with the same numeric identity.
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

ENV_SHA256_AFTER="$(sha256sum "${ENV_FILE}" | awk '{print $1}')"
[[ "${ENV_SHA256_BEFORE}" == "${ENV_SHA256_AFTER}" ]] \
  || die ".env ha cambiado durante 04-gitmem.sh"

log "working tree: ${MEMORY_DATA}"
log "origin: ${origin}"
log "branch: ${branch}"
log "MEMORY.md / USER.md: OK"
log ".env inmutable: OK"

cat <<EOF

Git-backed memory preparada y auditada.

Este script NO ha ejecutado pull/merge/rebase/commit/push.
La sincronizacion periodica se delegara a un scheduler containerizado en una fase posterior.
EOF
