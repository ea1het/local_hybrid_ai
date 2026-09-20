#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Persisted runtime inventory snapshot, owned by inventory.

Component compilation itself is shared core behaviour; this module only adds
the rescan-snapshot persistence and diffing that ``inventory`` alone needs.
"""
from __future__ import annotations
import hashlib,json,os
from pathlib import Path
from local_ai_cli.common import manifests as _manifests
from local_ai_cli.common.component_inventory import ComponentInventoryError,compile_components
ROOT=Path(__file__).resolve().parents[3];SCHEMA_VERSION=1
def runtime_root():return Path(os.environ.get("LOCAL_AI_RUNTIME_ROOT","/opt/docker/runtime"))
def snapshot_path():return runtime_root()/"platform"/"component-inventory.json"
def source_fingerprint():
 digest=hashlib.sha256()
 try:manifests=_manifests.all_manifests()
 except _manifests.ManifestError as exc:raise ComponentInventoryError(str(exc)) from exc
 for sid,manifest in sorted(manifests.items()):
  for name in ("manifest.json","docker-compose.yml"):
   path=ROOT/manifest["directory"]/name;digest.update(f"stack{sid}/{name}\0".encode());digest.update(path.read_bytes() if path.is_file() else b"");digest.update(b"\0")
 return f"sha256:{digest.hexdigest()}"
def snapshot():
 return {"schema_version":SCHEMA_VERSION,"source_fingerprint":source_fingerprint(),"components":[{"stack":i["stack"],"id":i["id"],"management_type":i["management"]["type"],"service":i.get("service"),"container":i.get("container"),"upgrade_visible":"upgrade" in i} for i in compile_components()]}
def read_snapshot():
 path=snapshot_path()
 if not path.is_file():return None
 try:data=json.loads(path.read_text(encoding="utf-8"))
 except (OSError,json.JSONDecodeError):return None
 return data if data.get("schema_version")==SCHEMA_VERSION and isinstance(data.get("components"),list) else None
def diff(previous,current):
 old={f"{i['stack']}/{i['id']}":i for i in (previous or {}).get("components",[]) if isinstance(i,dict) and i.get("stack") and i.get("id")};new={f"{i['stack']}/{i['id']}":i for i in current["components"]};return {"added":sorted(set(new)-set(old)),"removed":sorted(set(old)-set(new)),"changed":sorted(k for k in set(new)&set(old) if new[k]!=old[k])}
def write_snapshot(current):
 path=snapshot_path();path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(".tmp");tmp.write_text(json.dumps(current,indent=2,sort_keys=True)+"\n",encoding="utf-8");os.replace(tmp,path)
