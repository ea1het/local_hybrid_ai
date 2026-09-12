#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

CONTAINER="open-webui"
TIMEOUT_SECONDS="${OPENWEBUI_READY_TIMEOUT:-240}"
START="$(date +%s)"

[[ "$(id -u)" -eq 0 ]] || { echo "ERROR: ejecuta este script como root" >&2; exit 1; }
[[ "${TIMEOUT_SECONDS}" =~ ^[0-9]+$ ]] || { echo "ERROR: OPENWEBUI_READY_TIMEOUT invalido" >&2; exit 1; }

while true; do
  if ! docker inspect "${CONTAINER}" >/dev/null 2>&1; then
    echo "ERROR: falta el contenedor ${CONTAINER}" >&2
    exit 1
  fi

  running="$(docker inspect -f '{{.State.Running}}' "${CONTAINER}")"
  status="$(docker inspect -f '{{.State.Status}}' "${CONTAINER}")"
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${CONTAINER}")"

  if [[ "${running}" == "true" && "${health}" == "healthy" ]]; then
    echo "[stack7-ready] Open WebUI: READY (${status}/${health})"
    exit 0
  fi

  case "${status}" in
    exited|dead|removing)
      echo "ERROR: ${CONTAINER} entro en estado terminal ${status}" >&2
      exit 1
      ;;
  esac

  now="$(date +%s)"
  if (( now - START >= TIMEOUT_SECONDS )); then
    echo "ERROR: timeout esperando Open WebUI (${status}/${health})" >&2
    exit 1
  fi

  sleep 2
done
