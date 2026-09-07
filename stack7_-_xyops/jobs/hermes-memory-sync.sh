#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

REPO="/work/hermes-memory"
BRANCH="main"
EXPECTED_ORIGIN="ssh://git@gitea/ea1het/hermes-memory.git"

SSH_CONFIG="/run/hermes-memory-ssh/ssh_config"
LOCK_FILE="/tmp/hermes-memory-sync.lock"

HERMES_UID=10000
HERMES_GID=10000

log()  { printf '[hermes-memory-sync] %s\n' "$*"; }
die()  { printf '[hermes-memory-sync] ERROR: %s\n' "$*" >&2; exit 1; }

restore_permissions() {
    chown -R "${HERMES_UID}:${HERMES_GID}" "${REPO}" || true

    [[ -d "${REPO}" ]] &&
        chmod 0700 "${REPO}" || true

    for file in MEMORY.md USER.md; do
        [[ -f "${REPO}/${file}" ]] &&
            chmod 0640 "${REPO}/${file}" || true
    done
}

trap restore_permissions EXIT

for cmd in git ssh flock chown chmod date; do
    command -v "${cmd}" >/dev/null 2>&1 ||
        die "falta comando requerido: ${cmd}"
done

[[ -d "${REPO}/.git" ]] ||
    die "${REPO} no es un working tree Git"

[[ -f "${SSH_CONFIG}" ]] ||
    die "falta ${SSH_CONFIG}"

exec 9>"${LOCK_FILE}"
flock -n 9 ||
    die "ya existe otra sincronización en ejecución"

export HOME=/tmp
export GIT_SSH_COMMAND="ssh -F ${SSH_CONFIG}"

GIT=(
    git
    -c "safe.directory=${REPO}"
    -C "${REPO}"
)

origin="$("${GIT[@]}" remote get-url origin)"
[[ "${origin}" == "${EXPECTED_ORIGIN}" ]] ||
    die "origin inesperado: ${origin}"

branch="$("${GIT[@]}" branch --show-current)"
[[ "${branch}" == "${BRANCH}" ]] ||
    die "branch inesperada: ${branch}"

for file in MEMORY.md USER.md; do
    [[ -f "${REPO}/${file}" && ! -L "${REPO}/${file}" ]] ||
        die "${file} ausente, no regular o symlink"
done

# ---------------------------------------------------------------------------
# Refuse any working-tree change outside MEMORY.md and USER.md.
# ---------------------------------------------------------------------------

changed_paths="$(
    {
        "${GIT[@]}" diff --name-only
        "${GIT[@]}" diff --cached --name-only
        "${GIT[@]}" ls-files --others --exclude-standard
    } |
    sort -u |
    sed '/^$/d'
)"

if [[ -n "${changed_paths}" ]]; then
    while IFS= read -r path; do
        case "${path}" in
            MEMORY.md|USER.md)
                ;;
            *)
                die "cambio no autorizado en working tree: ${path}"
                ;;
        esac
    done <<< "${changed_paths}"
fi

dirty=false
if ! "${GIT[@]}" diff --quiet ||
   ! "${GIT[@]}" diff --cached --quiet ||
   [[ -n "$("${GIT[@]}" ls-files --others --exclude-standard)" ]]; then
    dirty=true
fi

log "fetch origin/${BRANCH}"
"${GIT[@]}" fetch --prune origin "${BRANCH}"

local_head="$("${GIT[@]}" rev-parse HEAD)"
remote_head="$("${GIT[@]}" rev-parse "origin/${BRANCH}")"

if [[ "${local_head}" == "${remote_head}" ]]; then

    if [[ "${dirty}" == true ]]; then
        log "remote y local alineados; creando commit de memoria"

        "${GIT[@]}" add -- MEMORY.md USER.md

        "${GIT[@]}" \
            -c user.name="Hermes Memory Scheduler" \
            -c user.email="nhi-hermes@local" \
            commit \
            -m "Sync Hermes memory $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

        log "push origin/${BRANCH}"
        "${GIT[@]}" push origin "HEAD:${BRANCH}"
    else
        log "sin cambios; no hay nada que sincronizar"
    fi

else

    if "${GIT[@]}" merge-base --is-ancestor "${local_head}" "${remote_head}"; then
        # Remote is ahead.
        if [[ "${dirty}" == true ]]; then
            die "origin/${BRANCH} está adelantado y existen cambios locales; no se hace merge/rebase automático"
        fi

        log "remote adelantado; aplicando fast-forward"
        "${GIT[@]}" merge --ff-only "origin/${BRANCH}"

    elif "${GIT[@]}" merge-base --is-ancestor "${remote_head}" "${local_head}"; then
        # Local is ahead.
        if [[ "${dirty}" == true ]]; then
            log "local adelantado y con nuevos cambios de memoria; creando commit"

            "${GIT[@]}" add -- MEMORY.md USER.md

            "${GIT[@]}" \
                -c user.name="Hermes Memory Scheduler" \
                -c user.email="nhi-hermes@local" \
                commit \
                -m "Sync Hermes memory $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
        fi

        log "local adelantado; haciendo push"
        "${GIT[@]}" push origin "HEAD:${BRANCH}"

    else
        die "historia Git divergente; requiere intervención manual"
    fi
fi

# ---------------------------------------------------------------------------
# Final verification.
# ---------------------------------------------------------------------------

"${GIT[@]}" fetch origin "${BRANCH}"

local_final="$("${GIT[@]}" rev-parse HEAD)"
remote_final="$("${GIT[@]}" rev-parse "origin/${BRANCH}")"

[[ "${local_final}" == "${remote_final}" ]] ||
    die "verificación final fallida: local y origin/${BRANCH} no coinciden"

[[ -z "$("${GIT[@]}" status --porcelain)" ]] ||
    die "working tree no quedó limpio"

log "sincronización completada correctamente"
log "HEAD=${local_final}"
