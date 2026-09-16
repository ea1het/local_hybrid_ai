# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Structured install facade consumed by the public ``local-ai`` CLI."""
from __future__ import annotations
import argparse, subprocess, sys
from commands import install
SCHEMA_VERSION="1"
def _parser():
    p=argparse.ArgumentParser(add_help=False);p.add_argument("stacks",nargs="+");m=p.add_mutually_exclusive_group();m.add_argument("--plan",action="store_true");m.add_argument("--dry-run",action="store_true");p.add_argument("--target",action="store_true");p.add_argument("--reconcile",action="store_true");p.add_argument("--yes",action="store_true");return p
def _error(code,message):return {"schema_version":SCHEMA_VERSION,"command":"install","success":False,"error":{"code":code,"message":message}}
def _action_record(action):return {"stack":f"stack{action.stack_id}","phase":action.phase,"reason":action.reason}
def build_payload(argv):
    try:
        args=_parser().parse_args(argv);execute_mode=not args.plan and not args.dry_run;install.preflight(execute_mode);manifests=install.all_manifests();lifecycle=install.load_lifecycle();install.validate_registry(manifests,lifecycle);requested=install.resolve_requested(args.stacks,manifests);plan=install.resolve_plan(args.stacks,args.target);actions,reconcile_ids,changed_stack_ids=install.build_actions(requested,plan,manifests,lifecycle,force_reconcile=args.reconcile)
    except (install.InstallerError,OSError,subprocess.CalledProcessError) as exc:return _error("INSTALL_ERROR",str(exc)),1
    except SystemExit:return _error("INSTALL_USAGE","invalid install arguments"),2
    result={"schema_version":SCHEMA_VERSION,"command":"install","success":True,"mode":"plan" if args.plan else ("dry-run" if args.dry_run else "execute"),"requested":[f"stack{x}" for x in requested],"resolved_stacks":[f"stack{x}" for x in plan],"changed_stacks":[f"stack{x}" for x in sorted(changed_stack_ids)],"reconcile_stacks":[f"stack{x}" for x in reconcile_ids],"actions":[_action_record(x) for x in actions],"executed":False}
    if not execute_mode:return result,0
    if not args.yes:return _error("INSTALL_CONFIRMATION_REQUIRED","execution requires --yes; inspect --plan or --dry-run first"),1
    cp=subprocess.run([sys.executable,str(install.ROOT/"commands"/"install.py"),*argv],cwd=install.ROOT,text=True,capture_output=True,check=False)
    if cp.returncode!=0:return _error("INSTALL_EXECUTION_FAILED",(cp.stderr or cp.stdout or "installer failed").strip()),cp.returncode
    result["executed"]=True;return result,0
def json_payload(argv):return build_payload(argv)
def main(argv):
    """Compatibility entry point; serialization remains centralized."""
    from commands import render
    result,rc=build_payload(argv);render.render_json(result);return rc
