#!/usr/bin/env python3
"""Inspect and verify a completed backup set containing Stack4 Gitea state."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import dr_archive
import dr_stack4_backup

class Stack4InspectError(RuntimeError): pass

def read_metadata(backup_set: Path) -> dict:
    path=backup_set/"backup.json"
    try:
        metadata=json.loads(path.read_text(encoding="utf-8")); dr_archive.validate_completed_metadata(metadata)
    except (OSError,json.JSONDecodeError,dr_archive.ArchiveBackupError) as exc:
        raise Stack4InspectError(f"cannot read valid backup.json: {exc}") from exc
    matches=[a for a in metadata.get("artifacts",[]) if a.get("stack_id")==4 and a.get("resource_id")==dr_stack4_backup.GITEA_RESOURCE_ID and a.get("strategy")=="gitea-native-dump"]
    if len(matches)!=1:
        raise Stack4InspectError("backup set must contain exactly one Stack4 Gitea native dump")
    return metadata

def verify_checksums(backup_set: Path)->None:
    checksum_file=backup_set/"checksums.sha256"
    if not checksum_file.is_file(): raise Stack4InspectError("checksums.sha256 is missing")
    expected={}
    for line in [line.strip() for line in checksum_file.read_text(encoding="utf-8").splitlines() if line.strip()]:
        parts=line.split(None,1)
        if len(parts)!=2 or not re.fullmatch(r"[0-9a-f]{64}",parts[0]): raise Stack4InspectError("invalid checksums.sha256 format")
        relative=parts[1].lstrip("* ")
        if relative.startswith("/") or ".." in Path(relative).parts: raise Stack4InspectError("unsafe checksum path")
        expected[relative]=parts[0]
    for relative,digest in expected.items():
        target=backup_set/relative
        if not target.is_file(): raise Stack4InspectError(f"checksummed file is missing: {relative}")
        if dr_archive.sha256_file(target)!=digest: raise Stack4InspectError(f"checksum mismatch: {relative}")

def classify_members(names:list[str])->dict[str,int]:
    counts={"database_like":0,"repositories_like":0,"lfs_like":0,"attachments_like":0,"packages_like":0,"custom_config_like":0,"other":0}
    for name in names:
        low=name.lower(); matched=False
        if any(token in low for token in ("gitea-db","database",".sql",".db")): counts["database_like"]+=1; matched=True
        if "repo" in low or low.startswith("repositories/"): counts["repositories_like"]+=1; matched=True
        if "lfs" in low: counts["lfs_like"]+=1; matched=True
        if "attachment" in low: counts["attachments_like"]+=1; matched=True
        if "package" in low: counts["packages_like"]+=1; matched=True
        if "custom" in low or "app.ini" in low: counts["custom_config_like"]+=1; matched=True
        if not matched: counts["other"]+=1
    return counts

def inspect_backup_set(backup_set:Path)->dict[str,object]:
    metadata=read_metadata(backup_set); verify_checksums(backup_set)
    artifact=next(a for a in metadata["artifacts"] if a.get("stack_id")==4 and a.get("resource_id")==dr_stack4_backup.GITEA_RESOURCE_ID)
    dump_path=backup_set/artifact["relative_path"]
    if not dump_path.is_file() or dump_path.stat().st_size!=artifact["size_bytes"]: raise Stack4InspectError("Gitea artifact is missing or has wrong size")
    if dr_archive.sha256_file(dump_path)!=artifact["sha256"]: raise Stack4InspectError("Gitea artifact SHA-256 does not match metadata")
    names=dr_stack4_backup.validate_gitea_dump(dump_path); counts=classify_members(names); top_levels=sorted({Path(name).parts[0] for name in names if Path(name).parts})
    return {"backup_set":str(backup_set),"gitea_dump":artifact["relative_path"],"zip_members":len(names),"top_level_entries":top_levels[:50],"categories":counts,"checksums_valid":True,"zip_integrity_valid":True,"live_runtime_modified":False,"container_restarted":False}
def main()->int:
    parser=argparse.ArgumentParser(); parser.add_argument("backup_set"); parser.add_argument("--json",action="store_true"); args=parser.parse_args()
    try: result=inspect_backup_set(Path(args.backup_set))
    except (Stack4InspectError,dr_stack4_backup.Stack4BackupError,dr_archive.ArchiveBackupError,OSError) as exc: print(f"ERROR: {exc}",file=sys.stderr); return 1
    print(json.dumps(result,indent=2,sort_keys=True) if args.json else f"DR Stack4 Gitea native dump inspection\n- backup set: {result['backup_set']}\n- ZIP members: {result['zip_members']}\n- checksums: PASS\n- ZIP integrity: PASS\n- live runtime modified: no\n- container restarted: no")
    return 0
if __name__=="__main__": raise SystemExit(main())