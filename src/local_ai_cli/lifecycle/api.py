# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Selective non-destructive runtime start/stop for one prepared stack."""
from __future__ import annotations
import os,subprocess
from dataclasses import dataclass
from pathlib import Path
from local_ai_cli.common import runtime as install
from local_ai_cli.common import stack_contracts
ROOT=Path(__file__).resolve().parents[3];SCHEMA_VERSION="1"
class RuntimeLifecycleError(RuntimeError):
 def __init__(self,code,message):super().__init__(message);self.code=code;self.message=message
@dataclass(frozen=True)
class RuntimeResult:
 action:str;stack_id:int;directory:str;containers:tuple[str,...]
 def as_dict(self):return stack_contracts.json_payload(self.stack_id,self.directory,schema_version=SCHEMA_VERSION,command=f"runtime.{self.action}",success=True,directory=self.directory,containers=list(self.containers))
def _required_containers(sid,lifecycle):return tuple(lifecycle["stacks"][str(sid)]["required_containers"])
def _owned_containers(manifest):return tuple(v.split(":",1)[1] for v in manifest.get("owns",[]) if isinstance(v,str) and v.startswith("container:"))
def _runtime_running(sid,lifecycle):
 required=_required_containers(sid,lifecycle);return bool(required) and all(install.is_running(install.container_state(n)) for n in required)
def _required_provider_ids(manifest):return {int(v) for v in manifest.get("requires",[])}
def _required_consumers(provider_sid,manifests,lifecycle):
 caps=set(manifests[provider_sid].get("provides",[]));out=[]
 for sid,manifest in manifests.items():
  if sid==provider_sid or not _runtime_running(sid,lifecycle):continue
  if provider_sid in _required_provider_ids(manifest) or bool(caps & set(manifest.get("consumes",[]))):out.append(sid)
 return sorted(out)
def _missing_required_providers(sid,manifests,lifecycle):return [p for p in sorted(_required_provider_ids(manifests[sid])) if _required_containers(p,lifecycle) and not _runtime_running(p,lifecycle)]
def _resolve_one(selector,manifests):
 try:values=install.resolve_requested([selector],manifests)
 except install.ManifestError as exc:raise RuntimeLifecycleError("STACK_UNKNOWN",str(exc)) from exc
 if len(values)!=1:raise RuntimeLifecycleError("STACK_SELECTOR_INVALID","exactly one stack selector is required")
 return values[0]
def _preflight():
 if os.geteuid()!=0:raise RuntimeLifecycleError("RUNTIME_ROOT_REQUIRED","stack start/stop requires root")
 manifests=install.all_manifests();lifecycle=install.load_lifecycle();install.validate_registry(manifests,lifecycle)
 try:install.run(["docker","compose","version"],capture=True)
 except (FileNotFoundError,subprocess.CalledProcessError) as exc:raise RuntimeLifecycleError("DOCKER_UNAVAILABLE","docker compose is unavailable") from exc
 return manifests,lifecycle
def execute(action,selector):
 if action not in {"start","stop"}:raise RuntimeLifecycleError("RUNTIME_ACTION_INVALID",f"unsupported runtime action: {action}")
 manifests,lifecycle=_preflight();sid=_resolve_one(selector,manifests);manifest=manifests[sid];required=_required_containers(sid,lifecycle);owned=_owned_containers(manifest)
 if not required:raise RuntimeLifecycleError("STACK_RUNTIME_EMPTY",f"stack{sid} has no managed runtime containers to {action}")
 directory=manifest["directory"];cwd=ROOT/directory
 if not install.stack_prepared(directory):raise RuntimeLifecycleError("STACK_NOT_PREPARED",f"stack{sid} is not PREPARED")
 if action=="stop":
  consumers=_required_consumers(sid,manifests,lifecycle)
  if consumers:raise RuntimeLifecycleError("STACK_HAS_ACTIVE_CONSUMERS",f"cannot stop stack{sid}; required consumers are running: {', '.join(f'stack{x}' for x in consumers)}")
 else:
  missing=_missing_required_providers(sid,manifests,lifecycle)
  if missing:raise RuntimeLifecycleError("STACK_DEPENDENCY_NOT_RUNNING",f"cannot start stack{sid}; required providers are not running: {', '.join(f'stack{x}' for x in missing)}")
 cp=install.run(["docker","compose",action],cwd=cwd,capture=True,check=False)
 if cp.returncode!=0:
  detail=(cp.stderr or cp.stdout or "").strip();raise RuntimeLifecycleError("STACK_RUNTIME_COMMAND_FAILED",f"stack{sid} docker compose {action} failed: {detail or 'no diagnostic output'}")
 if action=="start":
  try:install.wait_required_runtime(sid,lifecycle["stacks"][str(sid)])
  except install.ManifestError as exc:raise RuntimeLifecycleError("STACK_START_NOT_READY",str(exc)) from exc
 return RuntimeResult(action,sid,directory,owned)
def json_payload(action,selector):
 try:return execute(action,selector).as_dict()
 except (RuntimeLifecycleError,install.ManifestError,stack_contracts.StackContractError) as exc:
  code=exc.code if isinstance(exc,RuntimeLifecycleError) else "RUNTIME_INTERNAL_ERROR";message=exc.message if isinstance(exc,RuntimeLifecycleError) else str(exc);return {"schema_version":SCHEMA_VERSION,"command":f"runtime.{action}","success":False,"error":{"code":code,"message":message}}
def cli_text(payload):
 if not payload["success"]:return f"ERROR [{payload['error']['code']}]: {payload['error']['message']}"
 return f"{payload['stack']}: {payload['command'].split('.')[-1].upper()} PASS\n- directory: {payload['directory']}\n- containers: {', '.join(payload['containers'])}"
def main(action,selector,*,json_output=False):
 from local_ai_cli.common import render
 payload=json_payload(action,selector);render.render_json(payload) if json_output else render.render_cli(cli_text(payload));return 0 if payload["success"] else 1
