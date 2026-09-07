#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

WORKSPACE="/work/hermes-sandbox"

log()  { printf '[hermes-sandbox-audit] %s\n' "$*"; }
die()  { printf '[hermes-sandbox-audit] ERROR: %s\n' "$*" >&2; exit 1; }

for cmd in find du stat df awk sort wc; do
    command -v "$cmd" >/dev/null 2>&1 ||
        die "falta comando requerido: $cmd"
done

[[ -d "$WORKSPACE" ]] ||
    die "$WORKSPACE no existe"

[[ ! -L "$WORKSPACE" ]] ||
    die "$WORKSPACE no puede ser symlink"

log "workspace=$WORKSPACE"

echo
echo "=== filesystem ==="
df -h "$WORKSPACE"

echo
echo "=== workspace identity ==="
stat -c 'uid=%u gid=%g mode=%a path=%n' "$WORKSPACE"

echo
echo "=== total size ==="
du -sh "$WORKSPACE"

echo
echo "=== top-level objects ==="
find "$WORKSPACE" \
    -xdev \
    -mindepth 1 \
    -maxdepth 1 \
    -printf '%y  %u:%g  %m  %10s  %TY-%Tm-%Td %TH:%TM  %f\n' \
    | sort

echo
echo "=== top-level sizes ==="
find "$WORKSPACE" \
    -xdev \
    -mindepth 1 \
    -maxdepth 1 \
    -print0 |
while IFS= read -r -d '' path; do
    du -sh "$path"
done |
sort -h

echo
echo "=== protected persistent objects ==="

if [[ -d "$WORKSPACE/venv" && ! -L "$WORKSPACE/venv" ]]; then
    log "KEEP: venv"
else
    log "INFO: venv no existe"
fi

echo
echo "=== symlinks ==="
SYMLINK_COUNT="$(
    find "$WORKSPACE" \
        -xdev \
        -mindepth 1 \
        -type l \
        -printf '.' |
    wc -c
)"

printf 'count=%s\n' "$SYMLINK_COUNT"

find "$WORKSPACE" \
    -xdev \
    -mindepth 1 \
    -type l \
    -printf '%p -> %l\n' \
    | sort

echo
echo "=== special objects excluding symlinks ==="

SPECIAL="$(
    find "$WORKSPACE" \
        -xdev \
        -mindepth 1 \
        \( -type s -o -type p -o -type b -o -type c \) \
        -print
)"

if [[ -n "$SPECIAL" ]]; then
    printf '%s\n' "$SPECIAL"
    die "se han detectado objetos especiales inesperados"
else
    log "none"
fi

echo
echo "=== file age statistics ==="

for DAYS in 1 7 30; do
    COUNT="$(
        find "$WORKSPACE" \
            -xdev \
            -mindepth 1 \
            -type f \
            -mtime +"$DAYS" \
            -printf '.' |
        wc -c
    )"

    BYTES="$(
        find "$WORKSPACE" \
            -xdev \
            -mindepth 1 \
            -type f \
            -mtime +"$DAYS" \
            -printf '%s\n' |
        awk '{s += $1} END {print s + 0}'
    )"

    printf '> %2s days: %6s files, %12s bytes\n' \
        "$DAYS" "$COUNT" "$BYTES"
done

echo
echo "=== unclassified top-level objects ==="

UNKNOWN=0

while IFS= read -r -d '' path; do
    name="${path##*/}"

    case "$name" in
        venv)
            ;;
        *)
            printf 'OBSERVE: %s\n' "$name"
            UNKNOWN=$((UNKNOWN + 1))
            ;;
    esac
done < <(
    find "$WORKSPACE" \
        -xdev \
        -mindepth 1 \
        -maxdepth 1 \
        -print0
)

printf 'unclassified_count=%s\n' "$UNKNOWN"

echo
log "audit completed successfully"
