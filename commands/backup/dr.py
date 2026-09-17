#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Manifest-driven disaster-recovery planning and backup-plan orchestration."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from . import dr_preflight
except ImportError:  # direct private-script compatibility
    import dr_preflight

BACKUP_ROOT_ENV = dr_preflight.BACKUP_ROOT_ENV
BACKUP_SET_NAME_PATTERN = dr_preflight.BACKUP_SET_NAME_PATTERN
DEFAULT_BACKUP_ROOT = dr_preflight.DEFAULT_BACKUP_ROOT
DestinationPreflight = dr_preflight.DestinationPreflight
RecoveryError = dr_preflight.RecoveryError
RuntimeCheck = dr_preflight.RuntimeCheck
docker_state = dr_preflight.docker_state
ensure_docker_preflight = dr_preflight.ensure_docker_preflight
expand_runtime_path = dr_preflight.expand_runtime_path
gitea_help_flags = dr_preflight.gitea_help_flags
nearest_existing_parent = dr_preflight.nearest_existing_parent
owned_container = dr_preflight.owned_container
preflight_archive_source = dr_preflight.preflight_archive_source
preflight_backup_destination = dr_preflight.preflight_backup_destination
preflight_docker_service = dr_preflight.preflight_docker_service
preflight_external_config_source = dr_preflight.preflight_external_config_source
preflight_git_source = dr_preflight.preflight_git_source
preflight_gitea_source = dr_preflight.preflight_gitea_source
preflight_postgres_source = dr_preflight.preflight_postgres_source
preflight_runtime_resource = dr_preflight.preflight_runtime_resource
preflight_runtime_sources = dr_preflight.preflight_runtime_sources
read_dotenv_presence = dr_preflight.read_dotenv_presence
require_env_value = dr_preflight.require_env_value
resolve_backup_root = dr_preflight.resolve_backup_root
resolve_base_path = dr_preflight.resolve_base_path
runtime_resources = dr_preflight.runtime_resources

PACKAGE_ROOT = Path(__file__).resolve().parent
ROOT = PACKAGE_ROOT.parents[1]
MANIFEST_TOOL = ROOT / "stack0_-_platform" / "manifests.py"
BACKUP_SET_SCHEMA_VERSION = 1
ARTIFACT_EXTENSIONS = {"archive": ".tar", "postgres-custom-dump": ".dump", "gitea-native-dump": ".zip"}

@dataclass(frozen=True)
class RecoveryEntry:
    stack_id:int; directory:str; stack_mode:str; resource_id:str|None; resource_class:str|None; strategy:str|None; sensitive:bool|None; restore_phase:str|None; disposition:str
    def as_dict(self)->dict[str,object]: return {"stack_id":self.stack_id,"directory":self.directory,"stack_mode":self.stack_mode,"resource_id":self.resource_id,"resource_class":self.resource_class,"strategy":self.strategy,"sensitive":self.sensitive,"restore_phase":self.restore_phase,"disposition":self.disposition}
@dataclass(frozen=True)
class BackupArtifactPlan:
    stack_id:int; resource_id:str; strategy:str; sensitive:bool; restore_phase:str|None; relative_path:str
    def as_dict(self)->dict[str,object]: return {"stack_id":self.stack_id,"resource_id":self.resource_id,"strategy":self.strategy,"sensitive":self.sensitive,"restore_phase":self.restore_phase,"relative_path":self.relative_path}
@dataclass(frozen=True)
class BackupPrerequisitePlan:
    stack_id:int; resource_id:str; kind:str; strategy:str; sensitive:bool
    def as_dict(self)->dict[str,object]: return {"stack_id":self.stack_id,"resource_id":self.resource_id,"kind":self.kind,"strategy":self.strategy,"sensitive":self.sensitive}

def run_command(cmd:list[str])->subprocess.CompletedProcess[str]: return subprocess.run(cmd,cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
def run_manifest_tool(*args:str)->object:
    try: cp=subprocess.run([sys.executable,str(MANIFEST_TOOL),*args],cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
    except subprocess.CalledProcessError as exc:
        detail=(exc.stderr or exc.stdout or str(exc)).strip(); raise RecoveryError(f"manifest resolver failed: {detail}") from exc
    try:return json.loads(cp.stdout)
    except json.JSONDecodeError as exc:raise RecoveryError("manifest resolver returned invalid JSON") from exc
def load_manifests()->dict[int,dict]:
    raw=run_manifest_tool("list","--json")
    if not isinstance(raw,list):raise RecoveryError("manifest list is not an array")
    manifests={}
    for item in raw:
        if not isinstance(item,dict) or not isinstance(item.get("id"),int):raise RecoveryError("manifest list contains an invalid entry")
        manifests[item["id"]]=item
    return manifests
def resolve_plan(selectors:list[str],*,target:bool=False)->list[int]:
    raw=run_manifest_tool("resolve",*selectors,*(["--target"] if target else []),"--json")
    if not isinstance(raw,list) or not all(isinstance(v,int) for v in raw):raise RecoveryError("manifest resolver returned an invalid plan")
    return raw
def _recovery_resources(manifest:dict)->list[dict]:
    recovery=manifest.get("recovery") or {}; resources=recovery.get("resources") or []
    return [r for r in resources if isinstance(r,dict)]
def build_plan_entries(resolved:list[int],manifests:dict[int,dict])->list[RecoveryEntry]:
    entries=[]
    for sid in resolved:
        m=manifests[sid]; resources=_recovery_resources(m)
        if not resources: entries.append(RecoveryEntry(sid,m["directory"],m["mode"],None,None,None,None,None,"RECONSTRUCT"));continue
        for r in resources:
            strategy=r.get("strategy"); disposition="BACKUP" if strategy in ARTIFACT_EXTENSIONS else "REQUIRE" if strategy=="external-config" else "EXTERNAL" if strategy=="git" else "RECONSTRUCT"
            entries.append(RecoveryEntry(sid,m["directory"],m["mode"],r.get("id"),r.get("class"),strategy,r.get("sensitive"),r.get("restore_phase"),disposition))
    return entries
def artifact_relative_path(entry:RecoveryEntry)->str:
    if entry.disposition!="BACKUP" or not entry.resource_id or entry.strategy not in ARTIFACT_EXTENSIONS:raise RecoveryError("entry is not a backup artifact")
    return f"artifacts/stack{entry.stack_id}/{entry.resource_id}{ARTIFACT_EXTENSIONS[entry.strategy]}"
def build_backup_plan(entries:list[RecoveryEntry])->tuple[list[BackupArtifactPlan],list[BackupPrerequisitePlan]]:
    artifacts=[]; prerequisites=[]
    for e in entries:
        if e.disposition=="BACKUP": artifacts.append(BackupArtifactPlan(e.stack_id,e.resource_id or "",e.strategy or "",bool(e.sensitive),e.restore_phase,artifact_relative_path(e)))
        elif e.disposition in {"REQUIRE","EXTERNAL"}: prerequisites.append(BackupPrerequisitePlan(e.stack_id,e.resource_id or "",e.disposition,e.strategy or "",bool(e.sensitive)))
    return artifacts,prerequisites
def backup_plan_payload(requested,resolved,artifacts,prerequisites,*,source_commit,destination,runtime_checks):
    return {"schema_version":BACKUP_SET_SCHEMA_VERSION,"kind":"local-hybrid-ai-backup-plan","changes_made":False,"source_commit":source_commit,"requested":requested,"resolved_stacks":resolved,"destination":{**destination.as_dict(),"backup_set_name_pattern":BACKUP_SET_NAME_PATTERN},"layout":{"metadata":"backup.json","checksums":"checksums.sha256","artifacts":"artifacts/"},"artifacts":[a.as_dict() for a in artifacts],"prerequisites":[p.as_dict() for p in prerequisites],"runtime_preflight":[c.as_dict() for c in runtime_checks]}
def main(argv:list[str]|None=None)->int:
    parser=argparse.ArgumentParser(description="Plan manifest-driven disaster recovery");parser.add_argument("selectors",nargs="*",default=["all"]);parser.add_argument("--target",action="store_true");args=parser.parse_args(argv)
    try:
        manifests=load_manifests();resolved=resolve_plan(args.selectors,target=args.target);entries=build_plan_entries(resolved,manifests);print(json.dumps({"resolved_stacks":resolved,"entries":[e.as_dict() for e in entries]},indent=2,sort_keys=True));return 0
    except RecoveryError as exc:print(f"RECOVERY ERROR: {exc}",file=sys.stderr);return 2
if __name__=="__main__":raise SystemExit(main())
