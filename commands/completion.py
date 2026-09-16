# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Shell completion generation and explicit persistent installation."""
from __future__ import annotations
import os, re
from pathlib import Path
from commands import component_inventory, install

TOP_LEVEL = ("backup", "completion", "doctor", "install", "inventory", "restore", "start", "status", "stop", "upgrade")
GLOBAL_OPTIONS = ("--json", "--yes")
RESTORE_ACTIONS = ("apply", "drill", "list-backup-sets", "plan", "resume")
BACKUP_SET_RE = re.compile(r"^backup-\d{8}T\d{6}Z$")

def _stack_ids(): return [str(sid) for sid in sorted(install.all_manifests())]
def _backup_sets():
    root=Path(os.environ.get("DR_BACKUP_ROOT","/opt/local-hybrid-ai-backups")).expanduser()
    try: return sorted((str(p) for p in root.iterdir() if p.is_dir() and not p.is_symlink() and BACKUP_SET_RE.fullmatch(p.name)),reverse=True)
    except OSError: return []
def _upgrade_components(stack):
    if not stack.isdigit(): return []
    key=f"stack{int(stack)}"
    for record in component_inventory.compile_upgrade_catalog()["stacks"]:
        if record["id"]==key: return sorted(item["id"] for item in record["components"])
    return []

def _with_globals(values): return [*values, *GLOBAL_OPTIONS]
def _candidates(before):
    semantic=[x for x in before if x not in GLOBAL_OPTIONS]
    if not semantic: return _with_globals(list(TOP_LEVEL))
    command=semantic[0]; tail=semantic[1:]
    if command=="backup": return _with_globals(["--destination"])
    if command=="completion": return _with_globals(["bash","install","status","zsh"] if not tail else [])
    if command in {"doctor","status"}: return _with_globals([])
    if command in {"start","stop"}: return _with_globals(_stack_ids() if not tail else [])
    if command=="restore":
        if not tail: return _with_globals(list(RESTORE_ACTIONS))
        if len(tail)==1 and tail[0] in {"apply","drill","plan","resume"}: return _with_globals(_backup_sets())
        return _with_globals([])
    if command=="inventory": return _with_globals(["rescan"] if not tail else [])
    if command=="install": return _with_globals([])
    if command=="upgrade":
        if not tail: return _with_globals([*_stack_ids(),"adopt","check","--offline","policy"])
        if tail[0]=="adopt": return _with_globals(_stack_ids() if len(tail)==1 else [])
        if tail[0] in {"--offline","check"}: return _with_globals([])
        if tail[0]=="policy":
            if len(tail)==1:return _with_globals(_stack_ids())
            if len(tail)==2:return _with_globals(_upgrade_components(tail[1]))
            if len(tail)==3:return _with_globals(["clear","set"])
            return _with_globals([])
        stack=tail[0]
        if stack in _stack_ids():
            if len(tail)==1:return _with_globals(_upgrade_components(stack))
            if len(tail)==2:return _with_globals(["clear","select"])
            if len(tail)==4 and tail[2]=="select":return _with_globals(["--force"])
        return _with_globals([])
    return _with_globals([])

def complete(words):
    prefix=words[-1] if words else ""; before=words[:-1] if words else []
    seen=set(); out=[]
    for value in _candidates(before):
        if value.startswith(prefix) and value not in seen: seen.add(value); out.append(value)
    return out

def shell_script(shell):
    if shell=="bash": return r'''_local_ai_complete() {
    local cmd="${COMP_WORDS[0]}"; local -a args=(); local i
    for ((i=1; i<=COMP_CWORD; i++)); do args+=("${COMP_WORDS[i]}"); done
    mapfile -t COMPREPLY < <("$cmd" __complete "${args[@]}" 2>/dev/null)
}
complete -F _local_ai_complete local-ai ./local-ai
'''
    if shell=="zsh": return r'''#compdef local-ai
_local_ai_complete() {
    local cmd="${words[1]}"; local -a args; args=("${words[@]:1}"); local -a replies
    replies=("${(@f)$($cmd __complete "${args[@]}" 2>/dev/null)}"); _describe 'local-ai' replies
}
compdef _local_ai_complete local-ai ./local-ai
'''
    raise ValueError(f"unsupported shell: {shell}")
def detect_shell(environ=None):
    env=os.environ if environ is None else environ; name=Path(env.get("SHELL","")).name.lower()
    if name in {"bash","zsh"}:return name
    raise ValueError(f"unsupported shell: {name or 'unknown'}")
def completion_target(shell,*,euid=None,home=None):
    uid=os.geteuid() if euid is None else euid; h=Path.home() if home is None else home
    if shell=="bash":return Path("/etc/bash_completion.d/local-ai") if uid==0 else h/".local/share/bash-completion/completions/local-ai"
    if shell=="zsh":return Path("/usr/local/share/zsh/site-functions/_local-ai") if uid==0 else h/".local/share/zsh/site-functions/_local-ai"
    raise ValueError(f"unsupported shell: {shell}")
def install_completion(*,environ=None,euid=None,home=None):
    shell=detect_shell(environ); target=completion_target(shell,euid=euid,home=home); target.parent.mkdir(parents=True,exist_ok=True); content=shell_script(shell)
    if not target.exists() or target.read_text(encoding="utf-8")!=content:target.write_text(content,encoding="utf-8")
    return shell,target
def completion_status(*,environ=None,euid=None,home=None):
    shell=detect_shell(environ); target=completion_target(shell,euid=euid,home=home); return shell,target,target.is_file() and target.read_text(encoding="utf-8")==shell_script(shell)
def main(args):
    if len(args)==1 and args[0] in {"bash","zsh"}:print(shell_script(args[0]),end="");return 0
    if args==["install"]:
        try:shell,target=install_completion()
        except (OSError,ValueError) as exc:print(f"Completion installation failed: {exc}");return 1
        print(f"Detected shell: {shell}\nCompletion target: {target}\nInstalled: yes\nStatus: ready for new shell sessions");return 0
    if args==["status"]:
        try:shell,target,installed=completion_status()
        except (OSError,ValueError) as exc:print(f"Completion status failed: {exc}");return 1
        print(f"Shell: {shell}\nInstalled: {'yes' if installed else 'no'}\nTarget: {target}");return 0 if installed else 1
    print("Usage: ./local-ai completion <bash|zsh|install|status>");return 2
