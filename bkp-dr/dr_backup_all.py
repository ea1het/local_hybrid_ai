#!/usr/bin/env python3
"""Atomic manifest-driven full backup-set executor.

Recovery policy comes from manifests. For `all`, deployment discovery uses the
installer lifecycle's required containers, which are validated as manifest-owned.
A stack is considered deployed if at least one required container exists; this
also catches partially stopped/broken deployments instead of silently omitting
them. Stack0 is the mandatory platform base and is always included.

The operational .env is a global sensitive artifact by ADR-0001.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
from dataclasses import dataclass
from pathlib import Path

import dr
import dr_archive
import dr_filesystem
import dr_postgres_verify
import dr_stack3_backup
import dr_stack4_backup

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
LIFECYCLE_FILE = PROJECT_ROOT / "installer" / "lifecycle.json"
ENV_SOURCE = ROOT / ".env"
ENV_RELATIVE_PATH = "artifacts/global/operational.env"


class BackupAllError(RuntimeError): pass


@dataclass(frozen=True)
class CompletedBackupAll:
    path: Path; artifact_count: int; prerequisite_count: int; deployed_stacks: tuple[int, ...]
    def as_dict(self):
        return {"backup_set": str(self.path), "artifact_count": self.artifact_count,
                "prerequisite_count": self.prerequisite_count,
                "deployed_stacks": list(self.deployed_stacks), "published_atomically": True}


def load_lifecycle() -> dict:
    try: data = json.loads(LIFECYCLE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: raise BackupAllError(f"cannot read installer lifecycle: {exc}") from exc
    if data.get("schema_version") != 1 or not isinstance(data.get("stacks"), dict):
        raise BackupAllError("unsupported installer lifecycle contract")
    return data


def detect_deployed_stacks(manifests: dict[int, dict], runner=dr.run_command) -> list[int]:
    lifecycle = load_lifecycle()["stacks"]
    deployed = [0]
    for sid in sorted(manifests):
        if sid == 0: continue
        entry = lifecycle.get(str(sid))
        if not isinstance(entry, dict) or entry.get("directory") != manifests[sid]["directory"]:
            raise BackupAllError(f"stack{sid}: lifecycle/manifest mismatch")
        required = entry.get("required_containers")
        if not isinstance(required, list) or not required:
            raise BackupAllError(f"stack{sid}: cannot determine deployment without required containers")
        owned = {v.split(":",1)[1] for v in manifests[sid].get("owns",[]) if v.startswith("container:")}
        if not set(required).issubset(owned):
            raise BackupAllError(f"stack{sid}: lifecycle required containers are not manifest-owned")
        exists = False
        for name in required:
            cp = runner(["docker","inspect","-f","{{.State.Status}}",name])
            if cp.returncode == 0: exists = True; break
        if exists: deployed.append(sid)
    return deployed


def _resource_map(manifests, plan):
    return {(sid,r["id"]):r for sid in plan for r in manifests[sid]["recovery"].get("resources",[])}


def _copy_private(source: Path, destination: Path):
    if not source.is_file() or source.is_symlink(): raise BackupAllError("operational .env must resolve to a regular file")
    if source.stat().st_size <= 0: raise BackupAllError("operational .env is empty")
    fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with source.open("rb") as src, os.fdopen(fd,"wb",closefd=False) as dst:
            shutil.copyfileobj(src,dst,1024*1024); dst.flush(); os.fsync(dst.fileno())
    finally: os.close(fd)
    os.chmod(destination,0o600)
    if dr_archive.mode_of(destination)!=0o600: raise BackupAllError("operational .env backup is not mode 0600")


def _artifact_metadata(a,path):
    return {"stack_id":a.stack_id,"resource_id":a.resource_id,"strategy":a.strategy,"sensitive":a.sensitive,
            "restore_phase":a.restore_phase,"relative_path":a.relative_path,"sha256":dr_archive.sha256_file(path),
            "size_bytes":path.stat().st_size}


def _create_manifest_artifact(a,resource,values,base_path,destination):
    destination.parent.mkdir(mode=0o700,parents=True,exist_ok=True); os.chmod(destination.parent,0o700)
    source=resource["config"]["source"]
    if a.strategy=="archive":
        dr_archive.create_tar_archive(dr.expand_runtime_path(source["path"],base_path),destination); return
    if a.strategy=="postgres-custom-dump":
        database=dr_postgres_verify.validate_identifier(dr.require_env_value(values,source["database_env"],label="database configuration"),"database")
        dr_stack3_backup.create_postgres_dump(database,destination); return
    if a.strategy=="gitea-native-dump":
        members,stopped,restarted=dr_stack4_backup.create_gitea_dump_offline(destination)
        if not stopped or not restarted: raise BackupAllError("Gitea controlled-offline adapter did not complete stop/restart safely")
        if not members: raise BackupAllError("Gitea native dump contains no members")
        return
    raise BackupAllError(f"no executing adapter registered for recovery strategy: {a.strategy}")


def execute_backup_all(backup_root: Path) -> CompletedBackupAll:
    manifests=dr.load_manifests()
    deployed=detect_deployed_stacks(manifests)
    # Resolve required dependency closure only for what is actually deployed.
    selectors=[str(sid) for sid in deployed]
    plan=dr.resolve_plan(selectors)
    entries=dr.build_plan_entries(plan,manifests)
    artifacts,prerequisites=dr.build_backup_plan(entries)
    resources=_resource_map(manifests,plan)
    dr.preflight_runtime_sources(manifests,plan)
    dr_filesystem.validate_existing_root(backup_root)
    values=dr.read_dotenv_presence(ENV_SOURCE); base_path=dr.resolve_base_path(values)
    created_at,final_name=dr_archive.timestamp_parts(dr_archive.utc_now()); final=backup_root/final_name
    if final.exists(): raise BackupAllError(f"final backup-set name already exists: {final}")
    temp=backup_root/f".{final_name}.tmp-{secrets.token_hex(8)}"; old_umask=os.umask(0o077)
    try:
        dr_archive.mkdir_private(temp); dr_archive.mkdir_private(temp/"artifacts"); dr_archive.mkdir_private(temp/"artifacts"/"global")
        env_path=temp/ENV_RELATIVE_PATH; _copy_private(ENV_SOURCE,env_path)
        completed=[]
        for artifact in artifacts:
            resource=resources.get((artifact.stack_id,artifact.resource_id))
            if resource is None: raise BackupAllError(f"manifest resource disappeared: stack{artifact.stack_id} {artifact.resource_id}")
            path=temp/artifact.relative_path; _create_manifest_artifact(artifact,resource,values,base_path,path)
            if not path.is_file() or path.stat().st_size<=0: raise BackupAllError(f"backup adapter produced missing/empty artifact: {artifact.relative_path}")
            completed.append(_artifact_metadata(artifact,path))
        globals_=[{"resource_id":"operational-env","strategy":"file-copy","sensitive":True,"restore_phase":"pre-prepare",
                   "relative_path":ENV_RELATIVE_PATH,"sha256":dr_archive.sha256_file(env_path),"size_bytes":env_path.stat().st_size}]
        prereq=[item.as_dict() for item in prerequisites]
        base={"schema_version":1,"kind":"local-hybrid-ai-backup-set","created_at":created_at,"source_commit":dr.git_head(),
              "requested":["all"],"resolved_stacks":plan,"artifacts":completed,"prerequisites":prereq}
        dr_archive.validate_completed_metadata(base)
        metadata=dict(base); metadata["global_artifacts"]=globals_; metadata["deployed_stacks"]=deployed
        # deployed_stacks is execution evidence; keep it outside normative metadata until schema v2.
        metadata.pop("deployed_stacks")
        metadata_path=temp/"backup.json"; dr_archive.write_private(metadata_path,(json.dumps(metadata,indent=2,sort_keys=True)+"\n").encode())
        items=[(ENV_RELATIVE_PATH,dr_archive.sha256_file(env_path))]+[(str(a["relative_path"]),str(a["sha256"])) for a in completed]
        items.append(("backup.json",dr_archive.sha256_file(metadata_path)))
        dr_archive.write_private(temp/"checksums.sha256","".join(f"{h}  {p}\n" for p,h in items).encode())
        for relative,expected in items:
            if dr_archive.sha256_file(temp/relative)!=expected: raise BackupAllError(f"pre-publication checksum mismatch: {relative}")
        for directory in sorted([p for p in temp.rglob("*") if p.is_dir()],key=lambda p:len(p.parts),reverse=True): dr_archive.fsync_directory(directory)
        dr_archive.fsync_directory(temp); dr_archive.rename_noreplace(temp,final); dr_archive.fsync_directory(backup_root)
        return CompletedBackupAll(final,len(completed)+1,len(prerequisites),tuple(deployed))
    except Exception:
        dr_archive.cleanup_temp(temp); raise
    finally: os.umask(old_umask)
