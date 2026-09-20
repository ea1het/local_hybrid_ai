#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Isolated restore verifier for the Stack0 archive DR milestone."""
from __future__ import annotations
import argparse,hashlib,json,os,shutil,stat,sys,tarfile,tempfile
from dataclasses import dataclass
from pathlib import Path,PurePosixPath
from local_ai_cli.common import archive
DIR_MODE=0o700;FILE_MODE=0o600
class ArchiveRestoreError(RuntimeError): pass
@dataclass(frozen=True)
class RestoreVerificationResult:
    backup_set:Path;artifact:Path;restored_root_name:str;member_count:int;compared_to_source:bool;source_match:bool|None;temporary_cleanup:bool
    def as_dict(self): return {"backup_set":str(self.backup_set),"artifact":str(self.artifact),"restored_root_name":self.restored_root_name,"member_count":self.member_count,"compared_to_source":self.compared_to_source,"source_match":self.source_match,"temporary_cleanup":self.temporary_cleanup,"live_runtime_modified":False}
def sha256_file(path): return archive.sha256_file(path)
def safe_member_name(name):
    path=PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts: raise ArchiveRestoreError(f"unsafe archive member path: {name}")
    if path.parts[0]!="pki": raise ArchiveRestoreError(f"archive member is outside expected pki root: {name}")
    return path
def validate_symlink_target(member_path,target):
    target_path=PurePosixPath(target)
    if target_path.is_absolute(): raise ArchiveRestoreError(f"absolute symlink target is not allowed: {member_path}")
    depth=0
    for part in member_path.parent.joinpath(target_path).parts:
        if part==".": continue
        depth += -1 if part==".." else 1
        if depth<=0: raise ArchiveRestoreError(f"symlink escapes pki root: {member_path}")
def validate_completed_backup_set(backup_set):
    if not backup_set.is_dir(): raise ArchiveRestoreError(f"backup set is not a directory: {backup_set}")
    metadata_path=backup_set/"backup.json";checksums_path=backup_set/"checksums.sha256"
    if not metadata_path.is_file() or not checksums_path.is_file(): raise ArchiveRestoreError("backup set is missing metadata or checksum index")
    try:
        metadata=json.loads(metadata_path.read_text(encoding="utf-8"));legacy_view=dict(metadata);legacy_view.pop("global_artifacts",None);archive.validate_completed_metadata(legacy_view)
    except (OSError,json.JSONDecodeError,archive.ArchiveBackupError) as exc: raise ArchiveRestoreError(f"invalid backup metadata: {exc}") from exc
    candidates=[i for i in metadata.get("artifacts",[]) if i.get("stack_id")==0 and i.get("resource_id")=="platform-pki" and i.get("strategy")=="archive"]
    if len(candidates)!=1: raise ArchiveRestoreError("backup set must contain exactly one Stack0 platform-pki archive artifact")
    meta=candidates[0];artifact=backup_set/meta["relative_path"]
    try: resolved_set=backup_set.resolve(strict=True);resolved_parent=artifact.parent.resolve(strict=True)
    except OSError as exc: raise ArchiveRestoreError(f"cannot resolve backup-set paths: {exc}") from exc
    if resolved_set not in (resolved_parent,*resolved_parent.parents): raise ArchiveRestoreError("artifact path resolves outside backup set")
    if not artifact.is_file(): raise ArchiveRestoreError("archive artifact is missing")
    if artifact.stat().st_size!=meta["size_bytes"]: raise ArchiveRestoreError("archive size does not match backup metadata")
    if sha256_file(artifact)!=meta["sha256"]: raise ArchiveRestoreError("archive SHA-256 does not match backup metadata")
    expected={}
    try:
        for raw in checksums_path.read_text(encoding="utf-8").splitlines():
            if raw.strip(): digest,rel=raw.split("  ",1);expected[rel]=digest
    except (OSError,ValueError) as exc: raise ArchiveRestoreError(f"invalid checksum index: {exc}") from exc
    if expected.get(meta["relative_path"])!=meta["sha256"]: raise ArchiveRestoreError("checksum index does not match artifact metadata")
    if expected.get("backup.json")!=hashlib.sha256(metadata_path.read_bytes()).hexdigest(): raise ArchiveRestoreError("checksum index does not match backup.json")
    return metadata,artifact
def extract_archive_safely(artifact,destination):
    destination.mkdir(mode=DIR_MODE);os.chmod(destination,DIR_MODE)
    try:
        with tarfile.open(artifact,"r") as archive:
            members=archive.getmembers()
            if not members: raise ArchiveRestoreError("archive is empty")
            for member in members:
                rel=safe_member_name(member.name);target=destination.joinpath(*rel.parts)
                if member.isdir(): target.mkdir(parents=True,exist_ok=True);os.chmod(target,stat.S_IMODE(member.mode))
                elif member.isfile():
                    target.parent.mkdir(parents=True,exist_ok=True);source=archive.extractfile(member)
                    if source is None: raise ArchiveRestoreError(f"cannot read archive member: {member.name}")
                    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,FILE_MODE)
                    try:
                        while True:
                            chunk=source.read(1024*1024)
                            if not chunk: break
                            os.write(fd,chunk)
                        os.fsync(fd)
                    finally: os.close(fd);source.close()
                    os.chmod(target,stat.S_IMODE(member.mode))
                elif member.issym(): validate_symlink_target(rel,member.linkname);target.parent.mkdir(parents=True,exist_ok=True);os.symlink(member.linkname,target)
                elif member.islnk():
                    link=destination.joinpath(*safe_member_name(member.linkname).parts);target.parent.mkdir(parents=True,exist_ok=True)
                    if not link.exists(): raise ArchiveRestoreError(f"hardlink source missing: {member.name}")
                    os.link(link,target)
                else: raise ArchiveRestoreError(f"unsupported archive member type: {member.name}")
    except (OSError,tarfile.TarError) as exc: raise ArchiveRestoreError(f"archive extraction failed: {exc}") from exc
    root=destination/"pki"
    if not root.is_dir(): raise ArchiveRestoreError("restored archive does not contain pki root")
    return root,len(members)
def tree_fingerprint(root):
    result=[]
    for path in sorted(root.rglob("*")):
        st=path.lstat();item={"path":str(path.relative_to(root)),"mode":stat.S_IMODE(st.st_mode),"type":"symlink" if path.is_symlink() else "directory" if path.is_dir() else "file" if path.is_file() else "other"}
        if path.is_file() and not path.is_symlink(): item["sha256"]=sha256_file(path)
        if path.is_symlink(): item["target"]=os.readlink(path)
        result.append(item)
    return result
def verify_restore(backup_set,*,compare_source=None):
    _,artifact=validate_completed_backup_set(backup_set);temp_parent=Path(tempfile.mkdtemp(prefix="local-hybrid-ai-restore-test-"));os.chmod(temp_parent,DIR_MODE);source_match=None;member_count=0;root_name="pki"
    try:
        root,member_count=extract_archive_safely(artifact,temp_parent/"restore");root_name=root.name
        if compare_source is not None:
            if not compare_source.is_dir(): raise ArchiveRestoreError(f"compare source is not a directory: {compare_source}")
            source_match=tree_fingerprint(root)==tree_fingerprint(compare_source)
            if not source_match: raise ArchiveRestoreError("restored tree does not match comparison source")
    finally: shutil.rmtree(temp_parent,ignore_errors=False)
    return RestoreVerificationResult(backup_set,artifact,root_name,member_count,compare_source is not None,source_match,not temp_parent.exists())
def main():
    parser=argparse.ArgumentParser();parser.add_argument("backup_set");parser.add_argument("--compare-source");parser.add_argument("--json",action="store_true");args=parser.parse_args()
    try: result=verify_restore(Path(args.backup_set),compare_source=Path(args.compare_source) if args.compare_source else None)
    except (ArchiveRestoreError,OSError) as exc: print(f"ERROR: {exc}",file=sys.stderr);return 1
    print(json.dumps(result.as_dict(),indent=2) if args.json else f"DR Stack0 archive restore verification: PASS\n- backup set: {result.backup_set}\n- live runtime modified: no");return 0
if __name__=="__main__": raise SystemExit(main())
