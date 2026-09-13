#!/usr/bin/env python3
"""First executing DR adapter: bounded archive backup for Stack0 platform PKI."""
from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import errno
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path

import dr
import dr_filesystem

ROOT = Path(__file__).resolve().parent
BACKUP_SCHEMA = ROOT / "backup-set.schema.json"
DIR_MODE = 0o700
FILE_MODE = 0o600
RENAME_NOREPLACE = 1
AT_FDCWD = -100

class ArchiveBackupError(RuntimeError): pass

@dataclass(frozen=True)
class ArchiveArtifact:
    stack_id: int; resource_id: str; strategy: str; sensitive: bool; restore_phase: str | None; relative_path: str

@dataclass(frozen=True)
class CompletedBackupSet:
    path: Path; metadata_path: Path; checksums_path: Path; artifact_path: Path; artifact_sha256: str; artifact_size_bytes: int

def mode_of(path: Path) -> int: return stat.S_IMODE(path.stat().st_mode)
def fsync_file(path: Path) -> None:
    fd=os.open(path,os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)
def fsync_directory(path: Path) -> None: dr_filesystem.fsync_directory(path)
def mkdir_private(path: Path) -> None:
    path.mkdir(mode=DIR_MODE); os.chmod(path,DIR_MODE)
    if mode_of(path)!=DIR_MODE: raise ArchiveBackupError(f"directory is not mode 0700: {path}")
def write_private(path: Path,payload: bytes)->None:
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,FILE_MODE)
    try:
        view=memoryview(payload)
        while view:
            written=os.write(fd,view); view=view[written:]
        os.fsync(fd)
    finally: os.close(fd)
    if mode_of(path)!=FILE_MODE: raise ArchiveBackupError(f"private file is not mode 0600: {path}")
def sha256_file(path: Path)->str:
    digest=hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b""): digest.update(chunk)
    return digest.hexdigest()
def validate_archive_source(source: Path)->None:
    if not source.is_dir(): raise ArchiveBackupError(f"archive source must be a directory: {source}")
    found=False; pending=[source]
    while pending:
        directory=pending.pop()
        try: entries=list(os.scandir(directory))
        except OSError as exc: raise ArchiveBackupError(f"cannot inspect archive source {directory}: {exc}") from exc
        for entry in entries:
            found=True; st=entry.stat(follow_symlinks=False); kind=stat.S_IFMT(st.st_mode)
            if stat.S_ISDIR(kind): pending.append(Path(entry.path))
            elif stat.S_ISREG(kind) or stat.S_ISLNK(kind): continue
            else: raise ArchiveBackupError(f"archive source contains unsupported special file: {entry.path}")
    if not found: raise ArchiveBackupError(f"archive source is empty: {source}")
def create_tar_archive(source: Path,destination: Path)->None:
    validate_archive_source(source); old_umask=os.umask(0o077)
    try:
        with tarfile.open(destination,mode="x",format=tarfile.PAX_FORMAT,dereference=False) as archive: archive.add(source,arcname=source.name,recursive=True)
    except (OSError,tarfile.TarError) as exc: raise ArchiveBackupError(f"cannot create archive {destination}: {exc}") from exc
    finally: os.umask(old_umask)
    os.chmod(destination,FILE_MODE); fsync_file(destination)
    if mode_of(destination)!=FILE_MODE: raise ArchiveBackupError(f"archive is not mode 0600: {destination}")
def parse_created_at(value: str)->dt.datetime:
    try: parsed=dt.datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError as exc: raise ArchiveBackupError("backup metadata created_at is not valid ISO-8601") from exc
    if parsed.tzinfo is None: raise ArchiveBackupError("backup metadata created_at must include timezone")
    return parsed
def require_exact_keys(value: dict,required: set[str],where: str)->None:
    actual=set(value)
    if actual!=required:
        missing=required-actual; extra=actual-required; detail=[]
        if missing: detail.append("missing="+",".join(sorted(missing)))
        if extra: detail.append("extra="+",".join(sorted(extra)))
        raise ArchiveBackupError(f"{where} does not match schema fields ({'; '.join(detail)})")
def require_schema_keys(value: dict,required: set[str],allowed: set[str],where: str)->None:
    actual=set(value); missing=required-actual; extra=actual-allowed
    if missing or extra:
        detail=[]
        if missing: detail.append("missing="+",".join(sorted(missing)))
        if extra: detail.append("extra="+",".join(sorted(extra)))
        raise ArchiveBackupError(f"{where} does not match schema fields ({'; '.join(detail)})")
def _validate_artifact_fields(item: dict,schema: dict,index: int,where: str,*,stack_owned: bool)->None:
    required=set(schema["required"]); require_exact_keys(item,required,f"{where} {index}")
    if stack_owned and (type(item["stack_id"]) is not int or item["stack_id"]<0): raise ArchiveBackupError(f"{where} {index} stack_id is invalid")
    if not re.fullmatch(schema["properties"]["resource_id"]["pattern"],item["resource_id"]): raise ArchiveBackupError(f"{where} {index} resource_id is invalid")
    if item["strategy"] not in schema["properties"]["strategy"]["enum"]: raise ArchiveBackupError(f"{where} {index} strategy is invalid")
    if not isinstance(item["sensitive"],bool): raise ArchiveBackupError(f"{where} {index} sensitive is invalid")
    if item["restore_phase"] not in schema["properties"]["restore_phase"]["enum"]: raise ArchiveBackupError(f"{where} {index} restore_phase is invalid")
    if not re.fullmatch(schema["properties"]["relative_path"]["pattern"],item["relative_path"]): raise ArchiveBackupError(f"{where} {index} relative_path is invalid")
    if not re.fullmatch(schema["properties"]["sha256"]["pattern"],item["sha256"]): raise ArchiveBackupError(f"{where} {index} sha256 is invalid")
    if type(item["size_bytes"]) is not int or item["size_bytes"]<0: raise ArchiveBackupError(f"{where} {index} size_bytes is invalid")
def validate_completed_metadata(metadata: dict,schema_path: Path=BACKUP_SCHEMA)->None:
    try: schema=json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError) as exc: raise ArchiveBackupError(f"cannot read backup-set schema: {exc}") from exc
    top_required=set(schema["required"]); top_allowed=set(schema["properties"])
    require_schema_keys(metadata,top_required,top_allowed,"backup metadata")
    if type(metadata["schema_version"]) is not int: raise ArchiveBackupError("backup metadata schema_version must be integer")
    if metadata["schema_version"]!=schema["properties"]["schema_version"]["const"]: raise ArchiveBackupError("backup metadata schema_version is unsupported")
    if metadata["kind"]!=schema["properties"]["kind"]["const"]: raise ArchiveBackupError("backup metadata kind is invalid")
    parse_created_at(metadata["created_at"])
    if not re.fullmatch(schema["properties"]["source_commit"]["pattern"],metadata["source_commit"]): raise ArchiveBackupError("backup metadata source_commit is invalid")
    if not isinstance(metadata["requested"],list) or not metadata["requested"] or not all(isinstance(v,str) and v for v in metadata["requested"]): raise ArchiveBackupError("backup metadata requested is invalid")
    if not isinstance(metadata["resolved_stacks"],list) or not all(type(v) is int and v>=0 for v in metadata["resolved_stacks"]): raise ArchiveBackupError("backup metadata resolved_stacks is invalid")
    if not isinstance(metadata["artifacts"],list): raise ArchiveBackupError("backup metadata artifacts must be an array")
    artifact_schema=schema["$defs"]["artifact"]
    for index,artifact in enumerate(metadata["artifacts"]):
        if not isinstance(artifact,dict): raise ArchiveBackupError(f"artifact {index} must be an object")
        _validate_artifact_fields(artifact,artifact_schema,index,"artifact",stack_owned=True)
    if "global_artifacts" in metadata:
        if not isinstance(metadata["global_artifacts"],list): raise ArchiveBackupError("backup metadata global_artifacts must be an array")
        global_schema=schema["$defs"]["globalArtifact"]
        for index,artifact in enumerate(metadata["global_artifacts"]):
            if not isinstance(artifact,dict): raise ArchiveBackupError(f"global artifact {index} must be an object")
            _validate_artifact_fields(artifact,global_schema,index,"global artifact",stack_owned=False)
    prerequisite_schema=schema["$defs"]["prerequisite"]; prerequisite_required=set(prerequisite_schema["required"])
    if not isinstance(metadata["prerequisites"],list): raise ArchiveBackupError("backup metadata prerequisites must be an array")
    for index,prerequisite in enumerate(metadata["prerequisites"]):
        if not isinstance(prerequisite,dict): raise ArchiveBackupError(f"prerequisite {index} must be an object")
        require_exact_keys(prerequisite,prerequisite_required,f"prerequisite {index}")
        if prerequisite["kind"] not in prerequisite_schema["properties"]["kind"]["enum"]: raise ArchiveBackupError(f"prerequisite {index} kind is invalid")
        if prerequisite["strategy"] not in prerequisite_schema["properties"]["strategy"]["enum"]: raise ArchiveBackupError(f"prerequisite {index} strategy is invalid")
def rename_noreplace(source: Path,destination: Path)->None:
    libc=ctypes.CDLL(None,use_errno=True); renameat2=getattr(libc,"renameat2",None)
    if renameat2 is None: raise ArchiveBackupError("atomic no-replace publication requires renameat2 on this host")
    renameat2.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]; renameat2.restype=ctypes.c_int
    rc=renameat2(AT_FDCWD,os.fsencode(source),AT_FDCWD,os.fsencode(destination),RENAME_NOREPLACE)
    if rc==0:return
    err=ctypes.get_errno()
    if err==errno.EEXIST: raise ArchiveBackupError(f"final backup-set name already exists: {destination}")
    raise ArchiveBackupError(f"atomic backup publication failed: {os.strerror(err)}")
def cleanup_temp(temp: Path)->None:
    if temp.exists(): shutil.rmtree(temp); fsync_directory(temp.parent)
def utc_now()->dt.datetime:return dt.datetime.now(dt.timezone.utc)
def timestamp_parts(now: dt.datetime)->tuple[str,str]:
    utc=now.astimezone(dt.timezone.utc).replace(microsecond=0); return utc.isoformat().replace("+00:00","Z"),utc.strftime("backup-%Y%m%dT%H%M%SZ")

def execute_archive_backup_set(*,backup_root:Path,source:Path,source_commit:str,requested:list[str],resolved_stacks:list[int],artifact:ArchiveArtifact,prerequisites:list[dict[str,object]],now:dt.datetime|None=None)->CompletedBackupSet:
    dr_filesystem.validate_existing_root(backup_root); created_at,final_name=timestamp_parts(now or utc_now()); final=backup_root/final_name
    if final.exists():raise ArchiveBackupError(f"final backup-set name already exists: {final}")
    temp=backup_root/f".{final_name}.tmp-{secrets.token_hex(8)}"; old_umask=os.umask(0o077)
    try:
        mkdir_private(temp); artifacts_dir=temp/"artifacts"; mkdir_private(artifacts_dir); stack_dir=artifacts_dir/f"stack{artifact.stack_id}"; mkdir_private(stack_dir)
        artifact_path=temp/artifact.relative_path; create_tar_archive(source,artifact_path); artifact_hash=sha256_file(artifact_path); artifact_size=artifact_path.stat().st_size
        if artifact_size<=0:raise ArchiveBackupError("archive artifact is empty")
        metadata={"schema_version":1,"kind":"local-hybrid-ai-backup-set","created_at":created_at,"source_commit":source_commit,"requested":requested,"resolved_stacks":resolved_stacks,"artifacts":[{"stack_id":artifact.stack_id,"resource_id":artifact.resource_id,"strategy":artifact.strategy,"sensitive":artifact.sensitive,"restore_phase":artifact.restore_phase,"relative_path":artifact.relative_path,"sha256":artifact_hash,"size_bytes":artifact_size}],"prerequisites":prerequisites}
        validate_completed_metadata(metadata); metadata_path=temp/"backup.json"; write_private(metadata_path,(json.dumps(metadata,indent=2,sort_keys=True)+"\n").encode()); metadata_hash=sha256_file(metadata_path)
        checksums_path=temp/"checksums.sha256"; write_private(checksums_path,(f"{artifact_hash}  {artifact.relative_path}\n{metadata_hash}  backup.json\n").encode())
        for directory in (stack_dir,artifacts_dir,temp):fsync_directory(directory)
        rename_noreplace(temp,final); fsync_directory(backup_root)
        return CompletedBackupSet(final,final/"backup.json",final/"checksums.sha256",final/artifact.relative_path,artifact_hash,artifact_size)
    except Exception: cleanup_temp(temp); raise
    finally: os.umask(old_umask)
def select_stack0_archive(manifests:dict[int,dict],plan:list[int])->tuple[ArchiveArtifact,Path]:
    if plan!=[0]:raise ArchiveBackupError("this milestone enables real backup execution only for Stack0")
    resource=[r for r in manifests[0]["recovery"].get("resources",[]) if r["strategy"]=="archive"][0]; values=dr.read_dotenv_presence(ROOT/".env"); base_path=dr.resolve_base_path(values)
    return ArchiveArtifact(0,resource["id"],"archive",resource["sensitive"],resource["config"].get("restore",{}).get("phase"),f"artifacts/stack0/{resource['id']}.tar"),dr.expand_runtime_path(resource["config"]["source"]["path"],base_path)
def execute_stack0(selectors:list[str],destination:str|None)->CompletedBackupSet:
    manifests=dr.load_manifests(); plan=dr.resolve_plan(selectors); artifact,source=select_stack0_archive(manifests,plan); backup_root,destination_source=dr.resolve_backup_root(destination); dr.preflight_backup_destination(backup_root,destination_source); dr.preflight_runtime_sources(manifests,plan); dr_filesystem.ensure_backup_root(backup_root)
    return execute_archive_backup_set(backup_root=backup_root,source=source,source_commit=dr.git_head(),requested=selectors,resolved_stacks=plan,artifact=artifact,prerequisites=[])
def main()->int:
    parser=argparse.ArgumentParser(); parser.add_argument("stack"); parser.add_argument("--destination"); parser.add_argument("--json",action="store_true"); args=parser.parse_args()
    try: result=execute_stack0([args.stack],args.destination)
    except (ArchiveBackupError,dr.RecoveryError,dr_filesystem.FilesystemContractError,OSError) as exc: print(f"ERROR: {exc}",file=sys.stderr); return 1
    print(json.dumps({"status":"COMPLETED","backup_set":str(result.path)},indent=2) if args.json else f"DR archive backup: COMPLETED\n- backup set: {result.path}"); return 0
if __name__=="__main__": raise SystemExit(main())