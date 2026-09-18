# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Canonical stack runtime/lifecycle-registry helpers, shared by doctor, lifecycle and status."""
from __future__ import annotations
import json,shutil,subprocess,sys,time
from pathlib import Path
from .manifests import ManifestError,all_manifests,manifest_json
ROOT=Path(__file__).resolve().parents[3]
LIFECYCLE_FILE=ROOT/"src"/"local_ai_cli"/"install-lifecycle.json"
def run(cmd,*,cwd=ROOT,capture=False,check=True):return subprocess.run(cmd,cwd=cwd,text=True,stdout=subprocess.PIPE if capture else None,stderr=subprocess.PIPE if capture else None,check=check)
def load_lifecycle():
 try:data=json.loads(LIFECYCLE_FILE.read_text(encoding="utf-8"))
 except (OSError,json.JSONDecodeError) as exc:raise ManifestError(f"cannot read lifecycle registry: {exc}") from exc
 if data.get("schema_version")!=1 or not isinstance(data.get("stacks"),dict):raise ManifestError("unsupported src/local_ai_cli/install-lifecycle.json schema")
 return data
def validate_registry(manifests,lifecycle):
 entries=lifecycle["stacks"];expected={str(sid) for sid in manifests}
 if set(entries)!=expected:raise ManifestError("lifecycle registry stack ids do not exactly match manifests")
 for sid,manifest in manifests.items():
  entry=entries[str(sid)]
  if entry.get("directory")!=manifest["directory"]:raise ManifestError(f"stack{sid}: lifecycle directory disagrees with manifest")
  owned={v.split(":",1)[1] for v in manifest.get("owns",[]) if isinstance(v,str) and v.startswith("container:")};required=entry.get("required_containers")
  if not isinstance(required,list) or not all(isinstance(n,str) and n for n in required):raise ManifestError(f"stack{sid}: invalid required_containers registry")
  if not set(required).issubset(owned):raise ManifestError(f"stack{sid}: required_containers must be owned by the stack")
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
  if sid not in manifests:raise ManifestError(f"unknown stack selector: {token}")
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
  if terminal:raise ManifestError(f"stack{sid} required runtime failed before READY: "+", ".join(f"{n}={s}" for n,s in terminal.items()))
  if time.monotonic()>=deadline:raise ManifestError(f"stack{sid} required runtime did not become READY within {timeout_seconds}s: "+", ".join(f"{n}={s}" for n,s in states.items()))
  time.sleep(2)
