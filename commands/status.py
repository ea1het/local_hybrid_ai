# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Read-only operational status data for the Local Hybrid AI installation."""
from __future__ import annotations
import json
from pathlib import Path
from commands import component_state, install, upgrade
SCHEMA_VERSION="3"
class StatusError(RuntimeError): pass
_deployed_versions=component_state.deployed_versions;_deployed=component_state.deployed;_drift=component_state.drift;_is_floating_image_reference=component_state.is_floating_image_reference;_resolve_state=component_state.resolve_identity
def inventory(*,runtime_root:Path|None=None,deployed_versions:dict[str,str]|None=None):
    env=upgrade.read_env();records=upgrade.component_records()
    if deployed_versions is None:deployed_versions=component_state.deployed_versions(runtime_root or upgrade.runtime_root())
    rows=[]
    for component in upgrade.load_catalog():
        key=upgrade.key(component);actual_image=upgrade.running_image(component);record=records[key]
        if record.get("availability")=="local":actual="local" if actual_image else "n/a";desired="local";deployed="local" if actual_image else "unknown";drift="n/a"
        else:desired_image=upgrade.compose_image(component,env);desired,actual,drift=component_state.resolve_identity(component,desired_image,actual_image);deployed=component_state.deployed(key,desired,actual,deployed_versions)
        rows.append({"stack":component.stack,"component":component.name,"desired":desired,"deployed":deployed,"actual":actual,"drift":drift})
    return rows
def _stack_name(directory):
    name=directory.split("_-_",1)[1] if "_-_" in directory else directory;return name.replace("_","-")
def _runtime_summary(entry,state):
    if not state["prepared"]:return "unprepared","-"
    required=entry["required_containers"]
    if not required:return "prepared","ready"
    states=[state["containers"].get(n,"absent") for n in required];running=[install.is_running(v) for v in states];healthy=[install.is_runtime_healthy(v) for v in states]
    if all(running):return "running","ready" if all(healthy) else "degraded"
    if not any(running):return "stopped","-"
    return "partial","degraded"
def stack_inventory(component_rows=None):
    manifests=install.all_manifests();lifecycle=install.load_lifecycle();install.validate_registry(manifests,lifecycle);component_rows=inventory() if component_rows is None else component_rows;rows=[]
    for sid in sorted(manifests):
        manifest=manifests[sid];entry=lifecycle["stacks"][str(sid)];runtime=install.stack_state(manifest);state,health=_runtime_summary(entry,runtime);key=f"stack{sid}";owned=[r for r in component_rows if r["stack"]==key];rows.append({"stack":key,"name":_stack_name(manifest["directory"]),"state":state,"health":health,"drift":component_state.aggregate_drift(owned)})
    return rows
def json_payload():
    try:
        components=inventory();stacks=stack_inventory(components);return {"schema_version":SCHEMA_VERSION,"command":"status","success":True,"stacks":stacks,"components":components}
    except (component_state.ComponentStateError,install.InstallerError,StatusError,OSError,json.JSONDecodeError) as exc:return {"schema_version":SCHEMA_VERSION,"command":"status","success":False,"error":{"code":"STATUS_STATE_INVALID","message":str(exc)}}
def cli_text(payload):
    if not payload["success"]:return f"STATUS ERROR [STATUS_STATE_INVALID]: {payload['error']['message']}"
    headers=("STACK","NAME","STATE","HEALTH","DRIFT");values=[headers]+[(upgrade.human_stack_id(r["stack"]),r["name"],r["state"],r["health"],r["drift"]) for r in payload["stacks"]];widths=[max(len(str(row[i])) for row in values) for i in range(len(headers))];lines=[]
    for index,row in enumerate(values):
        lines.append("  ".join(str(value).ljust(widths[i]) for i,value in enumerate(row)))
        if index==0:lines.append("  ".join("-"*width for width in widths))
    return "\n".join(lines)
def main(*,json_output=False):
    from commands import render
    payload=json_payload();render.render_json(payload) if json_output else render.render_cli(cli_text(payload));return 0 if payload["success"] else 1
