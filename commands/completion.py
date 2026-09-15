# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Shell completion generation and explicit persistent installation."""

from __future__ import annotations

import os
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
        return ["bash", "install", "status", "zsh"] if not tail else []
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
            if len(tail) == 1:
                return _stack_ids()
            if len(tail) == 2:
                return _upgrade_components(tail[1])
            if len(tail) == 3:
                return ["clear", "set", "show"]
            return []
        stack = tail[0]
        if stack in _stack_ids():
            if len(tail) == 1:
                return _upgrade_components(stack)
            if len(tail) == 2:
                return ["clear", "select"]
            if len(tail) == 4 and tail[2] == "select":
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
    local -a args=()
    local i
    for ((i=1; i<=COMP_CWORD; i++)); do
        args+=("${COMP_WORDS[i]}")
    done
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


def detect_shell(environ: dict[str, str] | None = None) -> str:
    """Detect the operator shell without guessing unsupported shells."""
    env = os.environ if environ is None else environ
    name = Path(env.get("SHELL", "")).name.lower()
    if name in {"bash", "zsh"}:
        return name
    raise ValueError(f"unsupported shell: {name or 'unknown'}")


def completion_target(shell: str, *, euid: int | None = None, home: Path | None = None) -> Path:
    """Return the persistent target for a supported shell and privilege level."""
    uid = os.geteuid() if euid is None else euid
    user_home = Path.home() if home is None else home
    if shell == "bash":
        return Path("/etc/bash_completion.d/local-ai") if uid == 0 else user_home / ".local/share/bash-completion/completions/local-ai"
    if shell == "zsh":
        return Path("/usr/local/share/zsh/site-functions/_local-ai") if uid == 0 else user_home / ".local/share/zsh/site-functions/_local-ai"
    raise ValueError(f"unsupported shell: {shell}")


def install_completion(*, environ: dict[str, str] | None = None, euid: int | None = None, home: Path | None = None) -> tuple[str, Path]:
    """Install completion atomically enough for idempotent operator use."""
    shell = detect_shell(environ)
    target = completion_target(shell, euid=euid, home=home)
    target.parent.mkdir(parents=True, exist_ok=True)
    content = shell_script(shell)
    if not target.exists() or target.read_text(encoding="utf-8") != content:
        target.write_text(content, encoding="utf-8")
    return shell, target


def completion_status(*, environ: dict[str, str] | None = None, euid: int | None = None, home: Path | None = None) -> tuple[str, Path, bool]:
    shell = detect_shell(environ)
    target = completion_target(shell, euid=euid, home=home)
    installed = target.is_file() and target.read_text(encoding="utf-8") == shell_script(shell)
    return shell, target, installed


def main(args: list[str]) -> int:
    if len(args) == 1 and args[0] in {"bash", "zsh"}:
        print(shell_script(args[0]), end="")
        return 0
    if args == ["install"]:
        try:
            shell, target = install_completion()
        except (OSError, ValueError) as exc:
            print(f"Completion installation failed: {exc}")
            return 1
        print(f"Detected shell: {shell}")
        print(f"Completion target: {target}")
        print("Installed: yes")
        print("Status: ready for new shell sessions")
        return 0
    if args == ["status"]:
        try:
            shell, target, installed = completion_status()
        except (OSError, ValueError) as exc:
            print(f"Completion status failed: {exc}")
            return 1
        print(f"Shell: {shell}")
        print(f"Installed: {'yes' if installed else 'no'}")
        print(f"Target: {target}")
        return 0 if installed else 1
    print("Usage: ./local-ai completion <bash|zsh|install|status>")
    return 2
