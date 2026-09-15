# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Side-effect-free shell completion for the public ``local-ai`` CLI.

Completion is deliberately source-local: it reads the command grammar and
manifest-derived component inventory only. It never inspects Docker, reads or
writes runtime state, or contacts registries.
"""

from __future__ import annotations

import shlex
from pathlib import Path

from commands import component_inventory, install

TOP_LEVEL = (
    "backup", "completion", "doctor", "install", "inventory", "restore",
    "start", "status", "stop", "upgrade",
)
RESTORE_ACTIONS = ("apply", "drill", "plan", "resume")
UPGRADE_ACTIONS = ("adopt", "check", "policy")


def _stack_ids() -> list[str]:
    return [f"stack{sid}" for sid in sorted(install.all_manifests())]


def _upgrade_components(stack: str) -> list[str]:
    catalog = component_inventory.compile_upgrade_catalog()
    for record in catalog["stacks"]:
        if record["id"] == stack:
            return sorted(item["id"] for item in record["components"])
    return []


def _candidates(before: list[str]) -> list[str]:
    if not before:
        return list(TOP_LEVEL)
    command = before[0]
    tail = before[1:]

    if command == "completion":
        return ["bash", "zsh"] if not tail else []
    if command in {"start", "stop"}:
        return _stack_ids() if not tail else []
    if command == "restore":
        return list(RESTORE_ACTIONS) if not tail else []
    if command == "inventory":
        return ["rescan"] if not tail else []
    if command == "upgrade":
        if not tail:
            return ["--offline", "--yes", *UPGRADE_ACTIONS, *_stack_ids()]
        if tail[0] in {"--offline", "--yes", "check", "adopt"}:
            return []
        if tail[0] == "policy":
            return _stack_ids() if len(tail) == 1 else _upgrade_components(tail[1]) if len(tail) == 2 else ["clear", "set", "show"] if len(tail) == 3 else []
        stack = tail[0]
        if stack in _stack_ids():
            if len(tail) == 1:
                return _upgrade_components(stack)
            if len(tail) == 2:
                return ["clear", "select"]
            if len(tail) == 3 and tail[2] == "select":
                return ["--force"]
        return []
    return []


def complete(words: list[str]) -> list[str]:
    """Return newline-safe candidates for argv words including current prefix."""
    prefix = words[-1] if words else ""
    before = words[:-1] if words else []
    return sorted(value for value in _candidates(before) if value.startswith(prefix))


def shell_script(shell: str) -> str:
    """Render a shell adapter that delegates semantics to ``__complete``."""
    if shell == "bash":
        return r'''_local_ai_complete() {
    local cmd="${COMP_WORDS[0]}"
    local current="${COMP_WORDS[COMP_CWORD]}"
    local -a args=("${COMP_WORDS[@]:1:COMP_CWORD-1}" "$current")
    mapfile -t COMPREPLY < <("$cmd" __complete "${args[@]}" 2>/dev/null)
}
complete -F _local_ai_complete local-ai ./local-ai
'''
    if shell == "zsh":
        return r'''#compdef local-ai
_local_ai_complete() {
    local cmd="${words[1]}"
    local -a args
    args=("${words[@]:1}")
    local -a replies
    replies=("${(@f)$($cmd __complete "${args[@]}" 2>/dev/null)}")
    _describe 'local-ai' replies
}
compdef _local_ai_complete local-ai ./local-ai
'''
    raise ValueError(f"unsupported shell: {shell}")


def main(args: list[str]) -> int:
    if len(args) != 1 or args[0] not in {"bash", "zsh"}:
        print("Usage: ./local-ai completion <bash|zsh>")
        return 2
    print(shell_script(args[0]), end="")
    return 0
