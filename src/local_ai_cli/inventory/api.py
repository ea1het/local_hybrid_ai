#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Read-only source inventory validation and explicit rescan snapshot support."""
from __future__ import annotations
import sys
from local_ai_cli.common import render
from local_ai_cli.common.component_inventory import ComponentInventoryError
from . import component_inventory
SCHEMA_VERSION="1"
def _error(command,code,message):return {"schema_version":SCHEMA_VERSION,"command":command,"success":False,"error":{"code":code,"message":message}}
def json_payload(args=None):
 raw=list(args or [])
 if raw not in ([],["rescan"]):return _error("inventory","INVENTORY_USAGE","Usage: ./local-ai inventory [rescan]")
 rescan=raw==["rescan"];command="inventory.rescan" if rescan else "inventory"
 try:
  previous=component_inventory.read_snapshot();current=component_inventory.snapshot();changes=component_inventory.diff(previous,current)
  if rescan:component_inventory.write_snapshot(current)
 except (ComponentInventoryError,OSError) as exc:return _error(command,"INVENTORY_INVALID",str(exc))
 return {"schema_version":SCHEMA_VERSION,"command":command,"success":True,"source_fingerprint":current["source_fingerprint"],"components":current["components"],"changes":changes,"previous_snapshot":bool(previous),"snapshot_written":rescan}
def _human_stack_id(stack):return stack[5:] if stack.startswith("stack") else stack
def cli_text(payload):
 if not payload["success"]:return f"INVENTORY ERROR [{payload['error']['code']}]: {payload['error']['message']}"
 headers=("STACK","COMPONENT","TYPE","CONTAINER","UPGRADE");values=[headers]
 for c in payload["components"]:values.append((_human_stack_id(c["stack"]),c["id"],c["management_type"],c.get("container") or "-","yes" if c["upgrade_visible"] else "no"))
 widths=[max(len(str(row[i])) for row in values) for i in range(len(headers))];lines=[]
 for idx,row in enumerate(values):
  lines.append("  ".join(str(v).ljust(widths[i]) for i,v in enumerate(row)))
  if idx==0:lines.append("  ".join("-"*w for w in widths))
 lines.append("")
 lines.append(f"SOURCE FINGERPRINT  {payload['source_fingerprint']}")
 lines.append(f"COMPONENTS          {len(payload['components'])}")
 lines.append(f"PREVIOUS SNAPSHOT   {'yes' if payload['previous_snapshot'] else 'no'}")
 lines.append(f"SNAPSHOT WRITTEN    {'yes' if payload.get('snapshot_written') else 'no'}")
 lines.append("")
 for label in ("added","removed","changed"):
  changed=payload["changes"][label];lines.append(f"{label.upper():<8} {', '.join(changed) if changed else '-'}")
 return "\n".join(lines)
def main(args=None,*,json_output=False):
 payload=json_payload(args)
 if json_output:render.render_json(payload)
 elif payload["success"]:render.render_cli(cli_text(payload))
 else:print(cli_text(payload),file=sys.stderr)
 return 0 if payload["success"] else (2 if payload["error"]["code"]=="INVENTORY_USAGE" else 1)
