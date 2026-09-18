# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Component identity and drift semantics owned by the upgrade package."""
from __future__ import annotations
import json,re
from pathlib import Path
from . import registry as upgrade_registry
class ComponentStateError(RuntimeError):pass
def version_from_image(image):
 if not image:return "n/a"
 if "@sha256:" in image:
  base,digest=image.split("@sha256:",1);tag=base.rsplit(":",1)[1] if ":" in base.rsplit("/",1)[-1] else None;return f"{tag}@{digest[:12]}" if tag else f"sha256:{digest[:12]}"
 tail=image.rsplit("/",1)[-1];return tail.rsplit(":",1)[1] if ":" in tail else "latest"
def is_floating_image_reference(image):
 if not image or "${" in image or "@sha256:" in image:return False
 tag=upgrade_registry.parse_reference(image).tag
 if not tag:return True
 match=re.fullmatch(r"v?(\d+(?:\.\d+)*)(?:-[0-9A-Za-z][0-9A-Za-z._-]*)?",tag);return match is None or len(match.group(1).split("."))<3
def drift(desired,actual):
 if desired=="n/a":return "n/a"
 if actual=="n/a":return "yes"
 return "no" if desired==actual else "yes"
def resolve_identity(component,desired_image,actual_image):
 desired=version_from_image(desired_image);actual=version_from_image(actual_image);desired_floating=is_floating_image_reference(desired_image);actual_floating=is_floating_image_reference(actual_image)
 if desired=="n/a":return desired,actual,"n/a"
 if actual=="n/a":return desired,actual,"yes"
 if desired_floating:
  if not actual_image or not getattr(component,"container",None):return desired,actual,"n/a"
  try:state=upgrade_registry.inspect(component.container,actual_image,tracking_image=desired_image)
  except upgrade_registry.RegistryError:return desired,actual,"n/a"
  if state is None:return desired,actual,"n/a"
  desired_display=state.available_version or desired;actual_display=state.current_version or actual
  if state.local_digest and state.remote_digest:resolved="no" if state.local_digest==state.remote_digest else "yes"
  elif state.current_version and state.available_version:resolved="no" if state.current_version==state.available_version else "yes"
  else:resolved="n/a"
  return desired_display,actual_display,resolved
 if actual_floating and getattr(component,"container",None):
  try:state=upgrade_registry.inspect(component.container,actual_image)
  except upgrade_registry.RegistryError:return desired,actual,"n/a"
  if state is None or not state.current_version:return desired,actual,"n/a"
  actual=state.current_version
 return desired,actual,drift(desired,actual)
def deployed_versions(runtime_root:Path):
 path=runtime_root/"platform"/"upgrade-history.jsonl"
 if not path.is_file():return {}
 try:lines=path.read_text(encoding="utf-8").splitlines()
 except OSError as exc:raise ComponentStateError(f"cannot read upgrade history: {exc}") from exc
 deployed={}
 for number,line in enumerate(lines,start=1):
  if not line.strip():continue
  try:event=json.loads(line)
  except json.JSONDecodeError as exc:raise ComponentStateError(f"invalid upgrade history at line {number}") from exc
  if event.get("success") is not True:continue
  upgraded=event.get("upgraded",[])
  if not isinstance(upgraded,list):raise ComponentStateError(f"invalid successful upgrade history at line {number}")
  for item in upgraded:
   if not isinstance(item,dict):raise ComponentStateError(f"invalid successful upgrade history at line {number}")
   stack,component,version=item.get("stack"),item.get("component"),item.get("version")
   if all(isinstance(v,str) and v for v in (stack,component,version)):deployed[f"{stack}/{component}"]=version
 return deployed
def deployed(component_key,desired,actual,history):
 recorded=history.get(component_key)
 if recorded is not None:return recorded
 if desired=="n/a" and actual=="n/a":return "n/a"
 if actual!="n/a":return actual
 return "unknown"
def aggregate_drift(component_rows):
 values={row.get("drift","n/a") for row in component_rows}
 if "yes" in values:return "yes"
 if "no" in values:return "no"
 return "n/a"
