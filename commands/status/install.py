# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Package-local manifest/runtime helpers.

Intentionally duplicated while command packages are being isolated. Consolidate
only after the package boundaries and contracts are stable.
"""
from __future__ import annotations
import json,shutil,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
MANIFEST_TOOL=ROOT/"stack0_-_platform"/"manifests.py"
LIFECYCLE_FILE=ROOT/"commands"/"install-lifecycle.json"
class InstallerError(RuntimeError):pass
def run(cmd,*,cwd=ROOT,capture=False,check=True):return subprocess.run(cmd,cwd=cwd,text=True,stdout=subprocess.PIPE if capture else None,stderr=subprocess.PIPE if capture else None,check=check)
def manifest_json(*args):
 try:cp=run([sys.executable,str(MANIFEST_TOOL),*args],capture=True)
 except subprocess.CalledProcessError as exc:raise InstallerError(f"manifest resolver failed: {(exc.stderr or exc.stdout or str(exc)).strip()}") from exc
 try:return json.loads(cp.stdout)
 except json.JSONDecodeError as exc:raise InstallerError("manifest resolver returned invalid JSON") from exc
def all_manifests():
 raw=manifest_json("list","--json")
 if not isinstance(raw,list):raise InstallerError("manifest list is not an array")
 return {int(item["id"]):item for item in raw}
def load_lifecycle():
 try:data=json.loads(LIFECYCLE_FILE.read_text(encoding="utf-8"))
 except (OSError,json.JSONDecodeError) as exc:raise InstallerError(f"cannot read lifecycle registry: {exc}") from exc
 if data.get("schema_version")!=1 or not isinstance(data.get("stacks"),dict):raise InstallerError("unsupported commands/install-lifecycle.json schema")
 return data
def validate_registry(manifests,lifecycle):
 entries=lifecycle["stacks"];expected={str(sid) for sid in manifests}
 if set(entries)!=expected:raise InstallerError("lifecycle registry stack ids do not exactly match manifests")
 for sid,manifest in manifests.items():
  entry=entries[str(sid)]
  if entry.get("directory")!=manifest["directory"]:raise InstallerError(f"stack{sid}: lifecycle directory disagrees with manifest")
  owned={v.split(":",1)[1] for v in manifest.get("owns",[]) if isinstance(v,str) and v.startswith("container:")};required=entry.get("required_containers")
  if not isinstance(required,list) or not all(isinstance(n,str) and n for n in required):raise InstallerError(f"stack{sid}: invalid required_containers registry")
  if not set(required).issubset(owned):raise InstallerError(f"stack{sid}: required_containers must be owned by the stack")
def stack_prepared(directory):return (ROOT/directory/".lock").is_file()
def container_state(name):
 if shutil.which("docker") is None:return "unknown-no-docker"
 cp=run(["docker","inspect","-f","{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}",name],capture=True,check=False)
 if cp.returncode!=0:return "absent"
 status,_,health=cp.stdout.strip().partition("|");return f"{status}/{health}" if health else status or "unknown"
def is_running(state):return state=="running" or state.startswith("running/")
def is_runtime_healthy(state):return state in {"running","running/healthy"}
def stack_state(manifest):
 containers=[v.split(":",1)[1] for v in manifest.get("owns",[]) if isinstance(v,str) and v.startswith("container:")];return {"prepared":stack_prepared(manifest["directory"]),"containers":{name:container_state(name) for name in containers}}
def resolve_requested(selectors,manifests):
 if selectors==["all"]:return sorted(manifests)
 by_directory={data["directory"]:sid for sid,data in manifests.items()};out=[]
 for token in selectors:
  sid=int(token) if token.isdigit() else int(token[5:]) if token.startswith("stack") and token[5:].isdigit() else by_directory.get(token,-1)
  if sid not in manifests:raise InstallerError(f"unknown stack selector: {token}")
  if sid not in out:out.append(sid)
 return out
def wait_required_runtime(sid,entry,*,timeout_seconds=180):
 required=entry["required_containers"]
 if not required:return
 deadline=time.monotonic()+timeout_seconds
 while True:
  states={name:container_state(name) for name in required}
  if all(is_runtime_healthy(state) for state in states.values()):return
  terminal={name:state for name,state in states.items() if state in {"exited","dead","removing","absent"} or state.startswith(("exited/","dead/"))}
  if terminal:raise InstallerError(f"stack{sid} required runtime failed before READY: "+", ".join(f"{n}={s}" for n,s in terminal.items()))
  if time.monotonic()>=deadline:raise InstallerError(f"stack{sid} required runtime did not become READY within {timeout_seconds}s: "+", ".join(f"{n}={s}" for n,s in states.items()))
  time.sleep(2)
