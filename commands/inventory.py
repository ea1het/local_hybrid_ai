# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Read-only source inventory inspection and explicit consented snapshot rescan."""
from __future__ import annotations
from commands import component_inventory
SCHEMA_VERSION="1"
def _error(command,code,message):return {"schema_version":SCHEMA_VERSION,"command":command,"success":False,"error":{"code":code,"message":message}}
def json_payload(args=None,*,assume_yes=False):
 raw=list(args or [])
 if raw not in ([],["rescan"]):return _error("inventory","CLI_USAGE","usage: ./local-ai inventory [rescan]")
 command="inventory.rescan" if raw else "inventory.inspect"
 if raw and not assume_yes:return _error(command,"CONFIRMATION_REQUIRED","inventory rescan writes the runtime snapshot and requires --yes")
 try:
  previous=component_inventory.read_snapshot();current=component_inventory.snapshot();changes=component_inventory.diff(previous,current)
  if raw:component_inventory.write_snapshot(current)
 except (component_inventory.InventoryError,OSError) as exc:return _error(command,"INVENTORY_INVALID",str(exc))
 return {"schema_version":SCHEMA_VERSION,"command":command,"success":True,"source_fingerprint":current["source_fingerprint"],"components":current["components"],"changes":changes,"previous_snapshot":bool(previous),"snapshot_written":bool(raw)}
def cli_text(payload):
 if not payload["success"]:return f"INVENTORY ERROR [{payload['error']['code']}]: {payload['error']['message']}"
 lines=[f"SOURCE FINGERPRINT  {payload['source_fingerprint']}",f"COMPONENTS          {len(payload['components'])}",f"PREVIOUS SNAPSHOT   {'yes' if payload['previous_snapshot'] else 'no'}",f"SNAPSHOT WRITTEN    {'yes' if payload['snapshot_written'] else 'no'}",""]
 for label in ("added","removed","changed"):
  values=payload["changes"][label];lines.append(f"{label.upper():8} {len(values)}");lines.extend(f"  {v}" for v in values)
 lines.extend(["",("RESCAN: PASS" if payload["snapshot_written"] else "INSPECT: PASS")]);return "\n".join(lines)
def main(args=None,*,json_output=False,assume_yes=False):
 from commands import render
 payload=json_payload(args,assume_yes=assume_yes);render.render_json(payload) if json_output else render.render_cli(cli_text(payload));code=payload.get("error",{}).get("code");return 0 if payload["success"] else (2 if code in {"CLI_USAGE","CONFIRMATION_REQUIRED"} else 1)
