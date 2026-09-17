# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Read-only operational status data for the Local Hybrid AI installation."""
from __future__ import annotations
import json
from commands import install,stack_contracts,upgrade
SCHEMA_VERSION="4"
class StatusError(RuntimeError):pass
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
def stack_inventory():
 manifests=install.all_manifests();lifecycle=install.load_lifecycle();install.validate_registry(manifests,lifecycle);rows=[]
 for sid in sorted(manifests):
  manifest=manifests[sid];entry=lifecycle["stacks"][str(sid)];runtime=install.stack_state(manifest);state,health=_runtime_summary(entry,runtime)
  rows.append(stack_contracts.json_payload(sid,manifest["directory"],name=_stack_name(manifest["directory"]),state=state,health=health))
 return rows
def json_payload():
 try:return {"schema_version":SCHEMA_VERSION,"command":"status","success":True,"stacks":stack_inventory()}
 except (install.InstallerError,stack_contracts.StackContractError,StatusError,OSError,json.JSONDecodeError) as exc:return {"schema_version":SCHEMA_VERSION,"command":"status","success":False,"error":{"code":"STATUS_STATE_INVALID","message":str(exc)}}
def cli_text(payload):
 if not payload["success"]:return f"STATUS ERROR [STATUS_STATE_INVALID]: {payload['error']['message']}"
 headers=("STACK","NAME","STATE","HEALTH");values=[headers]+[(upgrade.human_stack_id(r["stack"]),r["name"],r["state"],r["health"]) for r in payload["stacks"]];widths=[max(len(str(row[i])) for row in values) for i in range(len(headers))];lines=[]
 for index,row in enumerate(values):
  lines.append("  ".join(str(value).ljust(widths[i]) for i,value in enumerate(row)))
  if index==0:lines.append("  ".join("-"*width for width in widths))
 return "\n".join(lines)
def main(*,json_output=False):
 from commands import render
 payload=json_payload();render.render_json(payload) if json_output else render.render_cli(cli_text(payload));return 0 if payload["success"] else 1
