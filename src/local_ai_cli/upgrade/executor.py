#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Guarded executor for explicitly selected component upgrades."""
from __future__ import annotations
import json, os, subprocess, time
from pathlib import Path
from . import inventory as upgrade_inventory
from . import policy as upgrade_policy
from . import registry as upgrade_registry
from . import runtime as upgrade_runtime
from local_ai_cli import backup as upgrade_backup

class UpgradeExecutionError(RuntimeError):
    def __init__(self, code: str, message: str, *, recovery_point: str | None = None):
        super().__init__(message); self.code=code; self.recovery_point=recovery_point

def _run(cmd:list[str],*,cwd:Path,capture:bool=False):
    cp=subprocess.run(cmd,cwd=cwd,text=True,stdout=subprocess.PIPE if capture else None,stderr=subprocess.PIPE if capture else None,check=False)
    if cp.returncode!=0:
        detail=(cp.stderr or cp.stdout or "").strip(); raise UpgradeExecutionError("UPGRADE_COMMAND_FAILED",f"command failed (rc={cp.returncode}): {' '.join(cmd)}"+(f": {detail}" if detail else ""))
    return cp

def _container_state(root,name):
    cp=subprocess.run(["docker","inspect","-f","{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}",name],cwd=root,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
    if cp.returncode!=0:return "absent"
    status,_,health=cp.stdout.strip().partition("|"); return f"{status}/{health}" if health else (status or "unknown")
def _running_image(root,container):return upgrade_runtime.running_container_image(root,container)
def _version_from_image(image):return upgrade_inventory.version_from_image(image)
def _healthy(state):return state in {"running","running/healthy"}
def _wait_ready(root,names,*,timeout_seconds=180):
    if not names:return
    deadline=time.monotonic()+timeout_seconds
    while True:
        last={name:_container_state(root,name) for name in names}
        if all(_healthy(v) for v in last.values()):return
        terminal={k:v for k,v in last.items() if v in {"absent","dead","exited"} or v.startswith("dead/") or v.startswith("exited/")}
        if terminal:raise UpgradeExecutionError("UPGRADE_READY_FAILED","required runtime failed before READY: "+", ".join(f"{k}={v}" for k,v in terminal.items()))
        if time.monotonic()>=deadline:raise UpgradeExecutionError("UPGRADE_READY_TIMEOUT","required runtime did not become READY: "+", ".join(f"{k}={v}" for k,v in last.items()))
        time.sleep(2)
def _load_json(path):
    try:return json.loads(path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError) as exc:raise UpgradeExecutionError("UPGRADE_INTERNAL_CONFIG",f"cannot read {path}: {exc}") from exc
def _read_env_values(path):
    try:lines=path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:raise UpgradeExecutionError("UPGRADE_ENV_READ_FAILED",f"cannot read operational .env: {exc}") from exc
    values={}
    for raw in lines:
        line=raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key,value=line.split("=",1); values[key.strip()]=value.strip().strip('"').strip("'")
    return values
def _atomic_update_env(path,updates):
    try:original=path.read_text(encoding="utf-8")
    except OSError as exc:raise UpgradeExecutionError("UPGRADE_ENV_READ_FAILED",f"cannot read operational .env: {exc}") from exc
    remaining=dict(updates); output=[]
    for raw in original.splitlines(keepends=True):
        stripped=raw.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key=stripped.split("=",1)[0].strip()
            if key in remaining:
                output.append(f"{key}={remaining.pop(key)}"+("\n" if raw.endswith("\n") else "")); continue
        output.append(raw)
    if remaining:raise UpgradeExecutionError("UPGRADE_ENV_KEY_MISSING","selected component version keys are missing from operational .env: "+", ".join(sorted(remaining)))
    tmp=path.with_name(path.name+".upgrade.tmp")
    try:tmp.write_text("".join(output),encoding="utf-8"); os.chmod(tmp,path.stat().st_mode); os.replace(tmp,path)
    except OSError as exc:
        try:tmp.unlink(missing_ok=True)
        except OSError:pass
        raise UpgradeExecutionError("UPGRADE_ENV_WRITE_FAILED",f"cannot update operational .env atomically: {exc}") from exc
def _target_image_ref(component_key,component,selection,env):
    apply=component.get("apply"); image_env_key=apply.get("image_env_key") if isinstance(apply,dict) else None
    if not isinstance(image_env_key,str) or not image_env_key:raise UpgradeExecutionError("UPGRADE_INTERNAL_CONFIG",f"component has no image_env_key for target preflight: {component_key}")
    repository=env.get(image_env_key)
    if not repository:raise UpgradeExecutionError("UPGRADE_ENV_KEY_MISSING",f"target image repository key is missing from operational .env: {image_env_key}")
    version=selection.get("version")
    if not isinstance(version,str) or not version:raise UpgradeExecutionError("UPGRADE_PLAN_INVALID",f"selected target version is invalid: {component_key}")
    try:return upgrade_registry.parse_reference(repository).with_tag(version)
    except upgrade_registry.RegistryError as exc:raise UpgradeExecutionError("UPGRADE_INTERNAL_CONFIG",f"invalid target image repository for {component_key}: {exc}") from exc
def _verify_selected_digest(component_key,image_ref,selection):
    selected_ref,selected_digest=selection.get("target_image"),selection.get("target_digest")
    if not all(isinstance(v,str) and v for v in (selected_ref,selected_digest)):raise UpgradeExecutionError("UPGRADE_PLAN_STALE",f"selected target has no immutable identity for {component_key}; reselect the target")
    if selected_ref!=image_ref:raise UpgradeExecutionError("UPGRADE_PLAN_STALE",f"target image reference changed for {component_key}: selected {selected_ref}, now {image_ref}")
    try:probe=upgrade_registry.manifest_probe(image_ref)
    except upgrade_registry.RegistryError as exc:raise UpgradeExecutionError("UPGRADE_TARGET_NOT_AVAILABLE",f"cannot resolve selected target {image_ref}: {exc}") from exc
    if probe.status!="ok" or not probe.digest:raise UpgradeExecutionError("UPGRADE_TARGET_NOT_AVAILABLE",f"selected target is not available: {image_ref} ({probe.status})")
    if probe.digest!=selected_digest:raise UpgradeExecutionError("UPGRADE_TARGET_MOVED",f"selected target tag moved for {component_key}: {selected_digest} -> {probe.digest}")
def _preflight_target_image(root,image_ref):
    try:cp=subprocess.run(["docker","manifest","inspect",image_ref],cwd=root,text=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=False)
    except OSError as exc:raise UpgradeExecutionError("UPGRADE_TARGET_PREFLIGHT_FAILED",f"cannot inspect target image {image_ref}: {exc}") from exc
    if cp.returncode!=0:
        detail=(cp.stderr or "").strip(); raise UpgradeExecutionError("UPGRADE_TARGET_NOT_AVAILABLE",f"target image is not available: {image_ref}"+(f": {detail}" if detail else ""))
def _recovery_point():
    payload=upgrade_backup.backup_payload()
    if not payload.get("success"):
        error=payload.get("error") or {}
        raise UpgradeExecutionError("UPGRADE_BACKUP_FAILED",f"backup engine failed: {error.get('message','backup operation failed')}")
    result=payload.get("result");path=result.get("backup_set") if isinstance(result,dict) else None
    if not isinstance(path,str) or not path:raise UpgradeExecutionError("UPGRADE_BACKUP_INVALID","backup engine returned an empty recovery-point path")
    return path
def _run_commands(root,directory,commands,*,quiet):
    cwd=root/directory
    for command in commands:
        cmd=list(command)
        if cmd[0].startswith("./"):cmd=["bash",cmd[0],*cmd[1:]]
        _run(cmd,cwd=cwd,capture=quiet)
def _load_manifests(root):
    result={}
    for path in sorted(root.glob("stack*_*/manifest.json")):
        data=_load_json(path); result[int(data["id"])]=data
    return result
def _stack_number(stack):
    if not stack.startswith("stack") or not stack[5:].isdigit():raise UpgradeExecutionError("UPGRADE_INTERNAL_CONFIG",f"invalid stack id: {stack}")
    return int(stack[5:])
def _prepared(root,manifest):return (root/manifest["directory"]/".lock").is_file()
def execute(*,root:Path,runtime_root:Path,selections:list[dict],components:dict[str,dict],plan_path:Path,quiet:bool=False)->dict:
    if not selections:raise UpgradeExecutionError("UPGRADE_NOTHING_SELECTED","no upgrades are selected")
    if os.geteuid()!=0:raise UpgradeExecutionError("UPGRADE_ROOT_REQUIRED","upgrade execution requires root")
    env_path=root/".env"
    if not env_path.is_file():raise UpgradeExecutionError("UPGRADE_ENV_MISSING",f"missing operational environment: {env_path}")
    lifecycle=_load_json(root/"src"/"local_ai_cli"/"install-lifecycle.json"); manifests=_load_manifests(root); env_values=_read_env_values(env_path); env_updates={}; affected_stacks=set(); recovery_required=False; target_images=[]
    for selection in selections:
        component_key=f"{selection['stack']}/{selection['component']}"; component=components.get(component_key)
        if component is None:raise UpgradeExecutionError("UPGRADE_COMPONENT_UNKNOWN",f"selected component is not in catalog: {component_key}")
        if not component.get("selectable",True):raise UpgradeExecutionError("UPGRADE_COMPONENT_NOT_SELECTABLE",f"selected component is not executable by policy: {component_key}")
        try:effective=upgrade_policy.effective_policy(runtime_root,component_key,component)[2]
        except upgrade_policy.PolicyError as exc:raise UpgradeExecutionError("UPGRADE_POLICY_INVALID",str(exc)) from exc
        current,target=selection.get("current_at_selection"),selection.get("version")
        if not isinstance(current,str) or not isinstance(target,str):raise UpgradeExecutionError("UPGRADE_PLAN_INVALID",f"selected versions are invalid: {component_key}")
        if not upgrade_policy.target_supported(effective,current,target):raise UpgradeExecutionError("UPGRADE_TARGET_UNSUPPORTED",f"selected target {target} is not permitted by {effective} policy for {component_key}")
        apply=component.get("apply")
        if not isinstance(apply,dict) or apply.get("type")!="env-version":raise UpgradeExecutionError("UPGRADE_COMPONENT_NOT_EXECUTABLE",f"component has no safe executor: {component_key}")
        env_key=apply.get("env_key")
        if not isinstance(env_key,str) or not env_key:raise UpgradeExecutionError("UPGRADE_INTERNAL_CONFIG",f"component has invalid env_key: {component_key}")
        env_updates[env_key]=selection["version"]; affected_stacks.add(_stack_number(selection["stack"])); recovery_required=recovery_required or bool(component.get("recovery_required",False)); image_ref=_target_image_ref(component_key,component,selection,env_values); _verify_selected_digest(component_key,image_ref,selection); target_images.append(image_ref)
    for image_ref in target_images:_preflight_target_image(root,image_ref)
    recovery_point=_recovery_point() if recovery_required else None
    try:
        _atomic_update_env(env_path,env_updates)
        for sid in sorted(affected_stacks):
            entry=lifecycle["stacks"][str(sid)]; selected_for_stack=[s for s in selections if _stack_number(s["stack"])==sid]
            for selection in selected_for_stack:
                component=components[f"{selection['stack']}/{selection['component']}"]; deploy=component["apply"].get("deploy")
                if not isinstance(deploy,list) or not deploy:raise UpgradeExecutionError("UPGRADE_INTERNAL_CONFIG",f"component has no targeted deploy command: {selection['stack']}/{selection['component']}")
                _run_commands(root,entry["directory"],[deploy],quiet=quiet)
            _wait_ready(root,entry["required_containers"]); _run_commands(root,entry["directory"],entry.get("reconcile",[]),quiet=quiet); _wait_ready(root,entry["required_containers"]); _run_commands(root,entry["directory"],entry.get("verify",[]),quiet=quiet)
            for selection in selected_for_stack:
                component=components[f"{selection['stack']}/{selection['component']}"]; actual=_version_from_image(_running_image(root,component["container"]))
                if actual!=selection["version"]:raise UpgradeExecutionError("UPGRADE_TARGET_NOT_RUNNING",f"{selection['stack']}/{selection['component']} expected {selection['version']} but runtime reports {actual}")
        reverified=[]
        for provider_sid in sorted(affected_stacks):
            provider_caps=set(manifests[provider_sid].get("provides",[]))
            for sid,manifest in manifests.items():
                if sid in affected_stacks or not _prepared(root,manifest):continue
                depends=provider_sid in set(manifest.get("requires",[]))|set(manifest.get("optional",[])); consumes=bool(provider_caps&(set(manifest.get("consumes",[]))|set(manifest.get("optional_consumes",[]))))
                if not(depends or consumes):continue
                entry=lifecycle["stacks"][str(sid)]; _run_commands(root,entry["directory"],entry.get("verify",[]),quiet=quiet)
                if sid not in reverified:reverified.append(sid)
        plan=_load_json(plan_path)
        for selection in selections:plan["selected"].pop(f"{selection['stack']}/{selection['component']}",None)
        tmp=plan_path.with_suffix(".tmp"); tmp.write_text(json.dumps(plan,indent=2,sort_keys=True)+"\n",encoding="utf-8"); os.replace(tmp,plan_path)
        history_path=runtime_root/"platform"/"upgrade-history.jsonl"; history_path.parent.mkdir(parents=True,exist_ok=True); event={"schema_version":1,"success":True,"recovery_point":recovery_point,"target_images":target_images,"upgraded":selections,"reverified_stacks":sorted(reverified)}
        with history_path.open("a",encoding="utf-8") as handle:handle.write(json.dumps(event,sort_keys=True)+"\n")
        return event
    except UpgradeExecutionError as exc:
        if exc.recovery_point is None:exc.recovery_point=recovery_point
        raise
