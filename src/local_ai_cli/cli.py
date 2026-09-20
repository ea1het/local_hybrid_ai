#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Public command dispatcher behind the root ``./local-ai`` entry point."""
from __future__ import annotations
import argparse,sys
from dataclasses import dataclass
from local_ai_cli import backup,completion,doctor,install_entry,inventory,lifecycle,restore,status,upgrade_adopt,upgrade_entry
from local_ai_cli.common import render
SCHEMA_VERSION="1"
class CLIUsageError(Exception):pass
class PublicArgumentParser(argparse.ArgumentParser):
 def error(self,message):raise CLIUsageError(message)
@dataclass(frozen=True)
class CLIContext:json_output:bool=False;assume_yes:bool=False
def _extract_global_options(argv):return [x for x in argv if x not in {"--json","--yes"}],CLIContext("--json" in argv,"--yes" in argv)
def _add_global_help(parser):
 parser.add_argument("--json",action="store_true",help="emit one machine-readable JSON document; valid before or after any public command");parser.add_argument("--yes",action="store_true",help="grant non-interactive consent for operations that require it; accepted as a no-op by read-only commands");return parser
def _leaf_parser(prog,description):return _add_global_help(PublicArgumentParser(prog=prog,description=description))
def _upgrade_help(path):
 if len(path)==1:upgrade_entry.public_parser().print_help();return
 leaf=path[1:]
 if leaf[0]=="check":
  p=_leaf_parser("local-ai upgrade check","Inspect installed and available component versions");p.add_argument("--offline",action="store_true",help="do not query upstream registries");p.print_help();return
 if leaf[0]=="adopt":_leaf_parser("local-ai upgrade adopt","Inspect the observed runtime baseline; use --yes to persist missing version-authority keys").print_help();return
 if leaf[0]=="policy":
  p=_leaf_parser("local-ai upgrade policy","Show or mutate the upgrade policy for one public stack/component");p.add_argument("stack",metavar="STACK",help="numeric public stack selector (0..7)");p.add_argument("component",nargs="?",metavar="COMPONENT",help="required when the stack has multiple components");p.add_argument("policy_action",nargs="?",metavar="ACTION",help="set POLICY or clear; omit to show policy");p.add_argument("policy",nargs="?",metavar="POLICY",choices=("manual","minor-series","major-series"),help="policy for ACTION=set: manual, minor-series or major-series");p.print_help();return
 if leaf[0]=="selectable":
  p=_leaf_parser("local-ai upgrade selectable","Show or override the selectable classification for one public stack/component");p.add_argument("stack",metavar="STACK",help="numeric public stack selector (0..7)");p.add_argument("component",nargs="?",metavar="COMPONENT",help="required when the stack has multiple components");p.add_argument("selectable_action",nargs="?",metavar="ACTION",choices=("enable","disable","clear"),help="enable or disable a durable override, or clear it; omit to show classification");p.print_help();return
 if leaf[0].isdigit():
  p=_leaf_parser("local-ai upgrade STACK [COMPONENT]","Stage or clear a component upgrade selection");p.add_argument("action",choices=("select","clear"),help="stage a VERSION or clear the staged selection");p.add_argument("version",nargs="?",metavar="VERSION",help="required by select");p.print_help();return
 upgrade_entry.public_parser().print_help()
def _public_help(argv):
 semantic=[arg for arg in argv if arg not in {"--json","--yes"}]
 if not semantic or semantic[-1] not in {"-h","--help"}:return False
 path=semantic[:-1]
 if not path:build_parser().print_help();return True
 if path[0]=="install":p=install_entry.parser();_add_global_help(p).print_help();return True
 if path[0]=="backup":build_backup_parser().print_help();return True
 if path[0]=="restore":build_restore_parser().parse_args([*path[1:],"--help"]);return True
 if path[0] in {"status","doctor"}:_leaf_parser(f"local-ai {path[0]}","Show operational status" if path[0]=="status" else "Diagnose management prerequisites and environment consistency").print_help();return True
 if path[0] in {"start","stop"}:
  p=_leaf_parser(f"local-ai {path[0]}",f"{path[0].capitalize()} one prepared stack runtime");p.add_argument("stack",metavar="STACK",help="numeric public stack selector (0..7)");p.print_help();return True
 if path[0]=="inventory":
  p=_leaf_parser("local-ai inventory","Validate and rescan manifest-declared component topology");p.add_argument("action",nargs="?",choices=("rescan",),help="rescan manifest-declared topology and persist the derived runtime snapshot");p.print_help();return True
 if path[0]=="completion":
  p=_leaf_parser("local-ai completion","Generate, install or inspect shell completion integration");p.add_argument("action",nargs="?",choices=("bash","zsh","install","status"));p.print_help();return True
 if path[0]=="upgrade":_upgrade_help(path);return True
 return False
def _json_error(code,message,*,command=None):
 payload={"schema_version":SCHEMA_VERSION,"success":False,"error":{"code":code,"message":message}}
 if command:payload["command"]=command
 render.render_json(payload)
def _usage_error(message,*,context,command=None):
 if context.json_output:_json_error("CLI_USAGE",message,command=command)
 else:print(f"ERROR [CLI_USAGE]: {message}",file=sys.stderr)
 return 2
def _confirmation_required(message,*,context,command):
 if context.json_output:_json_error("CONFIRMATION_REQUIRED",message,command=command)
 else:print(f"ERROR [CONFIRMATION_REQUIRED]: {message}",file=sys.stderr)
 return 2
def _require_mutation_consent(*,context,command,message=None):
 if context.assume_yes:return 0
 return _confirmation_required(message or f"{command} requires --yes",context=context,command=command)
def _stack_selector_error(token,*,context,command):
 message=f"stack selector must be a numeric id from 0 through 7, not {token!r}"
 if context.json_output:_json_error("STACK_SELECTOR_INVALID",message,command=command)
 else:print(f"ERROR [STACK_SELECTOR_INVALID]: {message}",file=sys.stderr)
 return 2
def _public_stack_id(token):return token.isdigit() and 0<=int(token)<=7
def _upgrade_public_args(args):
 if not args or args[0] in {"--offline","check","adopt"}:return list(args),None
 translated=list(args);pos=1 if translated[0] in ("policy","selectable") else 0
 if len(translated)<=pos:return translated,None
 token=translated[pos]
 if not _public_stack_id(token):return None,token
 translated[pos]=f"stack{int(token)}";return translated,None
def _render_owned(payload,context,api):
 if context.json_output:render.render_json(payload)
 else:render.render_cli(api.cli_text(payload))
 return 0 if payload.get("success") else 1
def build_backup_parser():
 p=_add_global_help(PublicArgumentParser(prog="local-ai backup",description="Create one atomic disaster-recovery backup set"));p.add_argument("--destination",help="backup root; defaults to DR_BACKUP_ROOT or /opt/local-hybrid-ai-backups");return p
def backup_command(args,context):
 try:ns=build_backup_parser().parse_args(args)
 except CLIUsageError as exc:return _usage_error(str(exc),context=context,command="backup")
 consent=_require_mutation_consent(context=context,command="backup",message="backup creation requires --yes")
 if consent:return consent
 return _render_owned(backup.backup_payload(ns.destination),context,backup)
def build_restore_parser():
 p=_add_global_help(PublicArgumentParser(prog="local-ai restore",description="Disaster-recovery operations for Local Hybrid AI"));a=p.add_subparsers(dest="restore_action",metavar="ACTION",parser_class=PublicArgumentParser)
 def action(name,**kwargs):return _add_global_help(a.add_parser(name,**kwargs))
 listing=action("list-backup-sets",help="list available recovery points");listing.add_argument("--backup-root");plan=action("plan",help="validate a recovery point and show restore ordering");plan.add_argument("backup_set");drill=action("drill",help="restore into an isolated destination and verify it");drill.add_argument("backup_set");drill.add_argument("--destination",required=True);apply=action("apply",help="preflight or execute a clean-target restore");apply.add_argument("backup_set");mode=apply.add_mutually_exclusive_group(required=True);mode.add_argument("--check-clean-target",action="store_true");mode.add_argument("--execute",action="store_true");apply.add_argument("--confirm-clean-target",action="store_true");apply.add_argument("--memory-sync-ssh-bootstrap");resume=action("resume",help="resume and verify an interrupted reconstructed target");resume.add_argument("backup_set");resume.add_argument("--memory-sync-ssh-bootstrap",required=True);return p
def restore_command(args,context):
 p=build_restore_parser()
 try:ns=p.parse_args(args)
 except CLIUsageError as exc:return _usage_error(str(exc),context=context,command="restore")
 if ns.restore_action is None:p.print_help();return 0
 action=ns.restore_action
 if action=="list-backup-sets":return _render_owned(restore.list_backup_sets_payload(ns.backup_root),context,restore)
 if action=="plan":return _render_owned(restore.plan_payload(ns.backup_set),context,restore)
 if action=="drill":
  consent=_require_mutation_consent(context=context,command="restore.drill",message="restore drill writes an isolated destination and requires --yes")
  if consent:return consent
  return _render_owned(restore.drill_payload(ns.backup_set,ns.destination),context,restore)
 if action=="apply":
  if ns.execute and not ns.confirm_clean_target:
   msg="restore apply --execute requires --confirm-clean-target"
   if context.json_output:_json_error("CONFIRMATION_REQUIRED",msg,command="restore.apply");return 2
   return _usage_error(msg,context=context,command="restore.apply")
  if ns.check_clean_target and ns.confirm_clean_target:return _usage_error("--confirm-clean-target is valid only with --execute",context=context,command="restore.apply")
  if ns.check_clean_target:return _render_owned(restore.check_clean_target_payload(ns.backup_set),context,restore)
  consent=_require_mutation_consent(context=context,command="restore.apply",message="restore execution requires --yes")
  if consent:return consent
  return _render_owned(restore.apply_payload(ns.backup_set,ns.memory_sync_ssh_bootstrap),context,restore)
 consent=_require_mutation_consent(context=context,command="restore.resume",message="restore resume mutates the reconstructed target and requires --yes")
 if consent:return consent
 return _render_owned(restore.resume_payload(ns.backup_set,ns.memory_sync_ssh_bootstrap),context,restore)
def build_parser():
 p=_add_global_help(PublicArgumentParser(prog="local-ai",description="Supported management CLI for the Local Hybrid AI installation"));sub=p.add_subparsers(dest="command",parser_class=PublicArgumentParser)
 for name,text in (("install","install or reconcile stacks"),("backup","create a recovery point"),("restore","list, plan, drill, apply or resume disaster recovery"),("status","show operational stack state, runtime health and drift"),("doctor","diagnose management prerequisites and environment consistency"),("inventory","validate and rescan manifest-declared component topology"),("completion","emit Bash or Zsh completion integration"),("upgrade","inspect versions and manage component upgrades")):_add_global_help(sub.add_parser(name,help=text))
 for action_name in ("start","stop"):
  r=_add_global_help(sub.add_parser(action_name,help=f"{action_name} one prepared stack runtime"));r.add_argument("stack")
 return p
def _upgrade_adopt(args,*,context):
 if args:return _usage_error("upgrade adopt takes no command-specific arguments",context=context,command="upgrade.adopt")
 try:
  payload=upgrade_adopt.json_payload(assume_yes=context.assume_yes);render.render_json(payload) if context.json_output else render.render_cli(upgrade_adopt.cli_text(payload));return 0
 except upgrade_adopt.AdoptionError as exc:
  payload={"schema_version":upgrade_adopt.SCHEMA_VERSION,"command":"upgrade.adopt","success":False,"error":{"code":exc.code,"message":str(exc)}}
  if context.json_output:render.render_json(payload)
  else:print(f"UPGRADE ERROR [{exc.code}]: {exc}",file=sys.stderr)
  return 1
def _render_upgrade(payload,rc,context):
 if context.json_output:render.render_json(payload)
 elif payload.get("success"):render.render_cli(upgrade_entry.cli_text(payload))
 else:print(upgrade_entry.cli_text(payload),file=sys.stderr)
 return rc
def _completion_command(args,context):
 payload,rc=completion.json_payload(args,assume_yes=context.assume_yes)
 if context.json_output:render.render_json(payload)
 elif payload.get("success"):render.render_cli(completion.cli_text(payload))
 else:print(completion.cli_text(payload),file=sys.stderr)
 return rc
def _upgrade_mutates(args):
 if not args:return False
 if args[0]=="policy":return "set" in args or args[-1:]==["clear"]
 if args[0]=="selectable":return "enable" in args or "disable" in args or args[-1:]==["clear"]
 return "select" in args or args[-1:]==["clear"]
def _confirm_upgrade_mutation(args,context):
 if not _upgrade_mutates(args) or context.assume_yes:return True
 _confirmation_required("upgrade state mutation requires --yes",context=context,command="upgrade");return False
def main(argv=None):
 original=list(sys.argv[1:] if argv is None else argv)
 if original and original[0]=="__complete":
  try:print("\n".join(completion.complete(original[1:])));return 0
  except Exception:return 0
 if _public_help(original):return 0
 raw,context=_extract_global_options(original)
 if raw and raw[0]=="completion":return _completion_command(raw[1:],context)
 if raw and raw[0]=="install":
  payload,rc=install_entry.json_payload(raw[1:],assume_yes=context.assume_yes)
  if context.json_output:render.render_json(payload)
  elif payload["success"]:render.render_cli(install_entry.cli_text(payload))
  else:print(f"INSTALL ERROR [{payload['error']['code']}]: {payload['error']['message']}",file=sys.stderr)
  return rc
 if raw and raw[0]=="backup":return backup_command(raw[1:],context)
 if raw and raw[0]=="restore":return restore_command(raw[1:],context)
 if raw and raw[0]=="inventory":
  if raw[1:]==["rescan"] and not context.assume_yes:return _confirmation_required("inventory rescan writes the derived runtime snapshot and requires --yes",context=context,command="inventory.rescan")
  payload=inventory.json_payload(raw[1:]);render.render_json(payload) if context.json_output else render.render_cli(inventory.cli_text(payload));return 0 if payload["success"] else (2 if payload.get("error",{}).get("code")=="INVENTORY_USAGE" else 1)
 if raw and raw[0]=="upgrade":
  if len(raw)>=2 and raw[1]=="adopt":return _upgrade_adopt(raw[2:],context=context)
  tail=raw[1:];confirm_data_migration="--confirm-data-migration" in tail;tail=[a for a in tail if a!="--confirm-data-migration"]
  args,invalid=_upgrade_public_args(tail)
  if invalid is not None:return _stack_selector_error(invalid,context=context,command="upgrade")
  if not _confirm_upgrade_mutation(args,context):return 2
  payload,rc=upgrade_entry.build_payload(args,apply_selected=context.assume_yes and not args,confirm_data_migration=confirm_data_migration);return _render_upgrade(payload,rc,context)
 try:ns=build_parser().parse_args(raw)
 except CLIUsageError as exc:return _usage_error(str(exc),context=context)
 if ns.command is None:p=build_parser();p.print_help();return 0
 if ns.command=="status":payload=status.json_payload();render.render_json(payload) if context.json_output else render.render_cli(status.cli_text(payload));return 0 if payload["success"] else 1
 if ns.command=="doctor":payload=doctor.json_payload();render.render_json(payload) if context.json_output else render.render_cli(doctor.cli_text(payload));return 0 if payload["success"] else 1
 if ns.command in {"start","stop"}:
  if not _public_stack_id(ns.stack):return _stack_selector_error(ns.stack,context=context,command=ns.command)
  consent=_require_mutation_consent(context=context,command=ns.command,message=f"{ns.command} mutates runtime state and requires --yes")
  if consent:return consent
  payload=lifecycle.json_payload(ns.command,ns.stack);render.render_json(payload) if context.json_output else render.render_cli(lifecycle.cli_text(payload));return 0 if payload["success"] else 1
 return _usage_error("unsupported command",context=context)