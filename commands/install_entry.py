# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Structured install facade consumed by the public ``local-ai`` CLI."""
from __future__ import annotations
import argparse,subprocess,sys
from commands import install
SCHEMA_VERSION="1"
class InstallArgumentParser(argparse.ArgumentParser):
 def error(self,message):raise ValueError(message)
def parser(*,add_help=True):
 p=InstallArgumentParser(prog="local-ai install",description="Install, plan, dry-run or reconcile manifest-declared stacks",add_help=add_help)
 p.add_argument("stacks",nargs="+",metavar="STACK",help="numeric public stack selector (0..7); multiple selectors are allowed")
 m=p.add_mutually_exclusive_group();m.add_argument("--plan",action="store_true",help="show the resolved lifecycle plan without executing it");m.add_argument("--dry-run",action="store_true",help="run installer validation without applying changes")
 p.add_argument("--target",action="store_true",help="limit dependency resolution to the requested target where supported");p.add_argument("--reconcile",action="store_true",help="force reconciliation of already prepared stacks");return p
def _parser():return parser(add_help=False)
def _error(code,message):return {"schema_version":SCHEMA_VERSION,"command":"install","success":False,"error":{"code":code,"message":message}}
def _action_record(action):return {"stack":f"stack{action.stack_id}","phase":action.phase,"reason":action.reason}
def _public_stack_ids(tokens):
 ids=[]
 for token in tokens:
  if not token.isdigit() or int(token) not in range(8):raise ValueError(f"stack selector must be a numeric id from 0 through 7, not {token!r}")
  ids.append(token)
 return ids
def build_payload(argv,*,assume_yes=False):
 try:
  args=_parser().parse_args(argv);_public_stack_ids(args.stacks);execute_mode=not args.plan and not args.dry_run;install.preflight(execute_mode);manifests=install.all_manifests();lifecycle=install.load_lifecycle();install.validate_registry(manifests,lifecycle);requested=install.resolve_requested(args.stacks,manifests);plan=install.resolve_plan(args.stacks,args.target);actions,reconcile_ids,changed_stack_ids=install.build_actions(requested,plan,manifests,lifecycle,force_reconcile=args.reconcile)
 except ValueError as exc:return _error("CLI_USAGE",str(exc)),2
 except (install.InstallerError,OSError,subprocess.CalledProcessError) as exc:return _error("INSTALL_ERROR",str(exc)),1
 result={"schema_version":SCHEMA_VERSION,"command":"install","success":True,"mode":"plan" if args.plan else ("dry-run" if args.dry_run else "execute"),"requested":[f"stack{x}" for x in requested],"resolved_stacks":[f"stack{x}" for x in plan],"changed_stacks":[f"stack{x}" for x in sorted(changed_stack_ids)],"reconcile_stacks":[f"stack{x}" for x in reconcile_ids],"actions":[_action_record(x) for x in actions],"executed":False}
 if not execute_mode:return result,0
 if not assume_yes:return _error("CONFIRMATION_REQUIRED","install execution requires --yes; inspect --plan or --dry-run first"),2
 cp=subprocess.run([sys.executable,str(install.ROOT/"commands"/"install.py"),*argv,"--yes"],cwd=install.ROOT,text=True,capture_output=True,check=False)
 if cp.returncode!=0:return _error("INSTALL_EXECUTION_FAILED",(cp.stderr or cp.stdout or "installer failed").strip()),cp.returncode
 result["executed"]=True;return result,0
def json_payload(argv,*,assume_yes=False):return build_payload(argv,assume_yes=assume_yes)
def cli_text(payload):
 if not payload.get("success"):return f"INSTALL ERROR [{payload['error']['code']}]: {payload['error']['message']}"
 lines=[f"INSTALL: {'PASS' if payload.get('executed') or payload.get('mode')!='execute' else 'READY'}",f"- mode: {payload['mode']}",f"- resolved stacks: {', '.join(payload['resolved_stacks']) or '-'}",f"- executed: {'yes' if payload['executed'] else 'no'}"]
 return "\n".join(lines)
def main(argv):
 from commands import render
 result,rc=build_payload(argv);render.render_json(result);return rc
