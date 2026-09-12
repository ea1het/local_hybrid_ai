#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

STACK0_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT_DIR="$(cd -- "${STACK0_DIR}/.." && pwd -P)"
MANIFESTS="${STACK0_DIR}/manifests.py"

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$#" -eq 1 ]] || fail "uso: $0 <stack-directory>"
DIRECTORY="$1"
[[ "${DIRECTORY}" =~ ^stack[0-9]+_-_[A-Za-z0-9._-]+$ ]] || fail "directorio de stack invalido: ${DIRECTORY}"
[[ -f "${MANIFESTS}" ]] || fail "falta ${MANIFESTS}"

if ! python3 "${MANIFESTS}" directories | grep -Fxq -- "${DIRECTORY}"; then
  fail "${DIRECTORY} no esta declarado por ningun manifest"
fi

ROOT_ENV="${ROOT_DIR}/.env"
TARGET_DIR="${ROOT_DIR}/${DIRECTORY}"
TARGET="${TARGET_DIR}/.env"

[[ -f "${ROOT_ENV}" && ! -L "${ROOT_ENV}" ]] || fail "el .env central debe ser un fichero regular: ${ROOT_ENV}"
[[ -d "${TARGET_DIR}" && ! -L "${TARGET_DIR}" ]] || fail "directorio de stack ausente o invalido: ${TARGET_DIR}"

if [[ -L "${TARGET}" ]]; then
  [[ "$(readlink "${TARGET}")" == "../.env" ]] || fail "${TARGET} apunta a un destino inesperado"
elif [[ -e "${TARGET}" ]]; then
  fail "${TARGET} existe pero no es el symlink gestionado"
else
  ln -s ../.env "${TARGET}"
fi

[[ -L "${TARGET}" && "$(readlink "${TARGET}")" == "../.env" ]] || fail "no se pudo asegurar ${TARGET}"
printf '%s -> ../.env\n' "${DIRECTORY}/.env"
