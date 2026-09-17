# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Private component inventory implementation owned by inventory."""
from __future__ import annotations
import hashlib,json,os,re,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];MANIFEST_TOOL=ROOT/"stack0_-_platform"/"manifests.py";SCHEMA_VERSION=1;MANAGEMENT_TYPES={"versioned","local","helper","platform"}
class InventoryError(RuntimeError):pass
def runtime_root():return Path(os.environ.get("LOCAL_AI_RUNTIME_ROOT","/opt/docker/runtime"))
def snapshot_path():return runtime_root()/"platform"/"component-inventory.json"
def all_manifests():
 try:cp=subprocess.run([sys.executable,str(MANIFEST_TOOL),"list","--json"],cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True);raw=json.loads(cp.stdout)
 except (subprocess.CalledProcessError,json.JSONDecodeError) as exc:raise InventoryError(f"manifest resolver failed: {exc}") from exc
 if not isinstance(raw,list):raise InventoryError("manifest list is not an array")
 return {int(item["id"]):item for item in raw}
def _compose_services(path):
 if not path.is_file():return set()
 services=set();inside=False
 for raw in path.read_text(encoding="utf-8").splitlines():
  if raw=="services:":inside=True;continue
  if inside and raw and not raw.startswith(" "):break
  if inside:
   match=re.match(r"^  ([A-Za-z0-9_.-]+):\s*$",raw)
   if match:services.add(match.group(1))
 return services
def compile_components():
 result=[];seen=set()
 for sid,manifest in sorted(all_manifests().items()):
  stack=f"stack{sid}";components=manifest.get("components")
  if not isinstance(components,list) or not components:raise InventoryError(f"{stack}: manifest components must be a non-empty list")
  owned={v.split(":",1)[1] for v in manifest.get("owns",[]) if isinstance(v,str) and v.startswith("container:")};declared=set();services=_compose_services(ROOT/manifest["directory"]/"docker-compose.yml")
  for raw in components:
   if not isinstance(raw,dict) or not isinstance(raw.get("id"),str):raise InventoryError(f"{stack}: invalid component")
   cid=raw["id"];key=f"{stack}/{cid}"
   if key in seen:raise InventoryError(f"duplicate component id: {key}")
   seen.add(key);management=raw.get("management")
   if not isinstance(management,dict) or management.get("type") not in MANAGEMENT_TYPES:raise InventoryError(f"{key}: invalid management.type")
   service=raw.get("service");container=raw.get("container")
   if container:
    if container not in owned:raise InventoryError(f"{key}: container {container} is not declared in manifest owns")
    if container in declared:raise InventoryError(f"{stack}: container {container} is declared by multiple components")
    declared.add(container)
   if service and service not in services:raise InventoryError(f"{key}: Compose service not found: {service}")
   result.append({"stack":stack,"id":cid,"management":dict(management),"service":service,"container":container,"upgrade":raw.get("upgrade")})
  missing=owned-declared
  if missing:raise InventoryError(f"{stack}: owned containers lack component semantics: {', '.join(sorted(missing))}")
 return result
def source_fingerprint():
 digest=hashlib.sha256()
 for sid,manifest in sorted(all_manifests().items()):
  for name in ("manifest.json","docker-compose.yml"):
   path=ROOT/manifest["directory"]/name;digest.update(f"stack{sid}/{name}\0".encode());digest.update(path.read_bytes() if path.is_file() else b"");digest.update(b"\0")
 return f"sha256:{digest.hexdigest()}"
def snapshot():
 return {"schema_version":SCHEMA_VERSION,"source_fingerprint":source_fingerprint(),"components":[{"stack":i["stack"],"id":i["id"],"management_type":i["management"]["type"],"service":i.get("service"),"container":i.get("container"),"upgrade_visible":isinstance(i.get("upgrade"),dict)} for i in compile_components()]}
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
