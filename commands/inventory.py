# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Read-only source inventory validation and explicit rescan snapshot support."""
from __future__ import annotations
from commands import component_inventory
SCHEMA_VERSION="1"
def json_payload(args=None):
    raw=list(args or [])
    if raw not in ([],["rescan"]): return {"schema_version":SCHEMA_VERSION,"command":"inventory.rescan","success":False,"error":{"code":"INVENTORY_USAGE","message":"Usage: ./local-ai inventory rescan"}}
    try:
        previous=component_inventory.read_snapshot(); current=component_inventory.snapshot(); changes=component_inventory.diff(previous,current); component_inventory.write_snapshot(current)
    except (component_inventory.InventoryError,OSError) as exc:
        return {"schema_version":SCHEMA_VERSION,"command":"inventory.rescan","success":False,"error":{"code":"INVENTORY_INVALID","message":str(exc)}}
    return {"schema_version":SCHEMA_VERSION,"command":"inventory.rescan","success":True,"source_fingerprint":current["source_fingerprint"],"components":current["components"],"changes":changes,"previous_snapshot":bool(previous)}
def cli_text(payload):
    if not payload["success"]: return payload["error"]["message"]
    lines=[f"SOURCE FINGERPRINT  {payload['source_fingerprint']}",f"COMPONENTS          {len(payload['components'])}",f"PREVIOUS SNAPSHOT   {'yes' if payload['previous_snapshot'] else 'no'}",""]
    for label in ("added","removed","changed"):
        values=payload["changes"][label]; lines.append(f"{label.upper():8} {len(values)}"); lines.extend(f"  {v}" for v in values)
    lines.extend(["","RESCAN: PASS"]); return "\n".join(lines)
def main(args=None,*,json_output=False):
    from commands import render
    payload=json_payload(args); render.render_json(payload) if json_output else render.render_cli(cli_text(payload)); return 0 if payload["success"] else (2 if payload.get("error",{}).get("code")=="INVENTORY_USAGE" else 1)
