#!/usr/bin/env bash
set -Eeuo pipefail

STACK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

bash "${STACK_DIR}/01-prepare.sh"
bash "${STACK_DIR}/verify.sh"
