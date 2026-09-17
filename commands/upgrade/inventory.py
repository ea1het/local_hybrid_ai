# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Package-private upgrade inventory presentation helpers."""
from __future__ import annotations
import re
from . import registry as upgrade_registry
def version_from_image(image:str|None)->str:
 if not image:return "n/a"
 if "@sha256:" in image:
  base,digest=image.split("@sha256:",1);tag=base.rsplit(":",1)[1] if ":" in base.rsplit("/",1)[-1] else None;return f"{tag}@{digest[:12]}" if tag else f"sha256:{digest[:12]}"
 tail=image.rsplit("/",1)[-1];return tail.rsplit(":",1)[1] if ":" in tail else "latest"
def execution_metadata(record:dict,*,selectable:bool)->dict:
 execution=record.get("execution")
 if isinstance(execution,dict):return dict(execution)
 return {"mode":"guarded"} if selectable else {"mode":"inventory-only","blocked_by":"legacy-or-synthetic-record"}
def registry_state(state):
 if state is None:return "n/a",None,None
 details={k:getattr(state,k) for k in ("image","registry","repository","tracking_image","local_digest","remote_digest","remote_status","tags_status","current_version","available_version","update_available")}
 if state.available_version:
  if state.current_version==state.available_version:return "current",details,state.current_version
  return state.available_version,details,state.current_version
 if state.update_available is True:return "update",details,state.current_version
 if state.update_available is False:return "current",details,state.current_version
 if state.remote_status=="not_tracked":return "pinned",details,state.current_version
 return "unknown",details,state.current_version
def human_stack_id(stack:str)->str:return stack[5:] if stack.startswith("stack") else stack
def human_available(row:dict)->str:
 value=row.get("available","n/a")
 if value in {"n/a","unchecked","pinned","unknown","current","update"}:return value
 return str(value)
