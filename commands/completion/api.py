# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Shell completion generation, discovery and structured management results."""
from __future__ import annotations
import os,re
from pathlib import Path
from commands import component_inventory,install
TOP_LEVEL=("backup","completion","doctor","install","inventory","restore","start","status","stop","upgrade");GLOBAL_OPTIONS=("--json","--yes");RESTORE_ACTIONS=("apply","drill","list-backup-sets","plan","resume");BACKUP_SET_RE=re.compile(r"^backup-\d{8}T\d{6}Z$");SCHEMA_VERSION="1"
def _stack_ids():return [str(sid) for sid in sorted(install.all_manifests())]
def _backup_sets():
 root=Path(os.environ.get("DR_BACKUP_ROOT","/opt/local-hybrid-ai-backups")).expanduser()
 try:return sorted((str(p) for p in root.iterdir() if p.is_dir() and not p.is_symlink() and BACKUP_SET_RE.fullmatch(p.name)),reverse=True)
 except OSError:return []
def _upgrade_components(stack):
 if not stack.isdigit():return []
 key=f"stack{int(stack)}"
 for record in component_inventory.compile_upgrade_catalog()["stacks"]:
  if record["id"]==key:return sorted(item["id"] for item in record["components"])
 return []
def _with_globals(values):return [*values,*GLOBAL_OPTIONS]
def _candidates(before):
 semantic=[x for x in before if x not in GLOBAL_OPTIONS];command=semantic[0] if semantic else None;tail=semantic[1:]
 if command is None:return _with_globals(list(TOP_LEVEL))
 if command=="backup":return _with_globals(["--destination"])
 if command=="completion":return _with_globals(["bash","install","status","zsh"] if not tail else [])
 if command in {"doctor","status"}:return _with_globals([])
 if command in {"start","stop"}:return _with_globals(_stack_ids() if not tail else [])
 if command=="restore":
  if not tail:return _with_globals(list(RESTORE_ACTIONS))
  action=tail[0]
  if action=="list-backup-sets":return _with_globals(["--backup-root"])
  if len(tail)==1 and action in {"apply","drill","plan","resume"}:return _with_globals(_backup_sets())
  if action=="drill" and len(tail)>=2:return _with_globals(["--destination"])
  if action=="apply" and len(tail)>=2:return _with_globals(["--check-clean-target","--execute","--confirm-clean-target","--memory-sync-ssh-bootstrap"])
  if action=="resume" and len(tail)>=2:return _with_globals(["--memory-sync-ssh-bootstrap"])
  return _with_globals([])
 if command=="inventory":return _with_globals(["rescan"] if not tail else [])
 if command=="install":return _with_globals([*_stack_ids(),"--plan","--dry-run","--target","--reconcile"])
 if command=="upgrade":
  if not tail:return _with_globals([*_stack_ids(),"adopt","check","--offline","policy"])
  if tail[0]=="adopt":return _with_globals([])
  if tail[0] in {"--offline","check"}:return _with_globals([])
  if tail[0]=="policy":
   if len(tail)==1:return _with_globals(_stack_ids())
   if len(tail)==2:return _with_globals(_upgrade_components(tail[1]))
   if len(tail)==3:return _with_globals(["clear","set"])
   if len(tail)>=4 and tail[-2]=="set":return _with_globals(["patch-series","minor-series","major-series"])
   return _with_globals([])
  stack=tail[0]
  if stack in _stack_ids():
   if len(tail)==1:return _with_globals(_upgrade_components(stack))
   if len(tail)==2:return _with_globals(["clear","select"])
   if len(tail)>=3 and "select" in tail:return _with_globals(["--force"])
 return _with_globals([])
def complete(words):
 prefix=words[-1] if words else "";before=words[:-1] if words else [];seen=set();out=[]
 for value in _candidates(before):
  if value.startswith(prefix) and value not in seen:seen.add(value);out.append(value)
 return out
def shell_script(shell):
 if shell=="bash":return '_local_ai_complete() {\n    local cmd="${COMP_WORDS[0]}"; local -a args=(); local i\n    for ((i=1; i<=COMP_CWORD; i++)); do args+=("${COMP_WORDS[i]}"); done\n    mapfile -t COMPREPLY < <("$cmd" __complete "${args[@]}" 2>/dev/null)\n}\ncomplete -F _local_ai_complete local-ai ./local-ai\n'
 if shell=="zsh":return '#compdef local-ai\n_local_ai_complete() {\n    local cmd="${words[1]}"; local -a args; args=("${words[@]:1}"); local -a replies\n    replies=("${(@f)$($cmd __complete "${args[@]}" 2>/dev/null)}"); _describe \'local-ai\' replies\n}\ncompdef _local_ai_complete local-ai ./local-ai\n'
 raise ValueError(f"unsupported shell: {shell}")
def detect_shell(environ=None):
 env=os.environ if environ is None else environ;name=Path(env.get("SHELL","")).name.lower()
 if name in {"bash","zsh"}:return name
 raise ValueError(f"unsupported shell: {name or 'unknown'}")
def completion_target(shell,*,euid=None,home=None):
 uid=os.geteuid() if euid is None else euid;h=Path.home() if home is None else home
 if shell=="bash":return Path("/etc/bash_completion.d/local-ai") if uid==0 else h/".local/share/bash-completion/completions/local-ai"
 if shell=="zsh":return Path("/usr/local/share/zsh/site-functions/_local-ai") if uid==0 else h/".local/share/zsh/site-functions/_local-ai"
 raise ValueError(f"unsupported shell: {shell}")
def install_completion(*,environ=None,euid=None,home=None):
 shell=detect_shell(environ);target=completion_target(shell,euid=euid,home=home);target.parent.mkdir(parents=True,exist_ok=True);content=shell_script(shell)
 if not target.exists() or target.read_text(encoding="utf-8")!=content:target.write_text(content,encoding="utf-8")
 return shell,target
def completion_status(*,environ=None,euid=None,home=None):
 shell=detect_shell(environ);target=completion_target(shell,euid=euid,home=home);return shell,target,target.is_file() and target.read_text(encoding="utf-8")==shell_script(shell)
def json_payload(args,*,assume_yes=False):
 try:
  if len(args)==1 and args[0] in {"bash","zsh"}:return {"schema_version":SCHEMA_VERSION,"command":"completion.script","success":True,"shell":args[0],"script":shell_script(args[0])},0
  if args==["install"]:
   if not assume_yes:return {"schema_version":SCHEMA_VERSION,"command":"completion.install","success":False,"error":{"code":"CONFIRMATION_REQUIRED","message":"completion installation requires --yes"}},2
   shell,target=install_completion();return {"schema_version":SCHEMA_VERSION,"command":"completion.install","success":True,"shell":shell,"target":str(target),"installed":True},0
  if args==["status"]:
   shell,target,installed=completion_status();return {"schema_version":SCHEMA_VERSION,"command":"completion.status","success":installed,"shell":shell,"target":str(target),"installed":installed},0 if installed else 1
  return {"schema_version":SCHEMA_VERSION,"command":"completion","success":False,"error":{"code":"COMPLETION_USAGE","message":"usage: local-ai completion <bash|zsh|install|status>"}},2
 except (OSError,ValueError) as exc:return {"schema_version":SCHEMA_VERSION,"command":"completion","success":False,"error":{"code":"COMPLETION_ERROR","message":str(exc)}},1
def cli_text(payload):
 if not payload["success"]:
  if payload.get("command")=="completion.status" and not payload.get("installed"):return f"Shell: {payload['shell']}\nInstalled: no\nTarget: {payload['target']}"
  return f"COMPLETION ERROR [{payload['error']['code']}]: {payload['error']['message']}"
 if payload["command"]=="completion.script":return payload["script"].rstrip("\n")
 if payload["command"]=="completion.install":return f"Detected shell: {payload['shell']}\nCompletion target: {payload['target']}\nInstalled: yes\nStatus: ready for new shell sessions"
 return f"Shell: {payload['shell']}\nInstalled: yes\nTarget: {payload['target']}"
def main(args):
 from commands import render
 payload,rc=json_payload(args,assume_yes=True);render.render_cli(cli_text(payload));return rc
