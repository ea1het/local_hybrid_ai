# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Core upgrade inventory, plan persistence and component metadata helpers."""
from __future__ import annotations
import os,time
from dataclasses import dataclass
from pathlib import Path
from . import component_inventory
from . import cache as upgrade_cache
from . import catalog as upgrade_catalog
from . import inventory as upgrade_inventory
from . import plan as upgrade_plan
from . import policy as upgrade_policy
from . import registry as upgrade_registry
from . import runtime as upgrade_runtime
ROOT=Path(__file__).resolve().parents[2]
SCHEMA_VERSION="1";REGISTRY_CACHE_SCHEMA_VERSION=upgrade_cache.SCHEMA_VERSION;REGISTRY_CACHE_DEFAULT_TTL_SECONDS=upgrade_cache.DEFAULT_TTL_SECONDS;REGISTRY_CACHE_MAX_ENTRIES=upgrade_cache.MAX_ENTRIES
class UpgradeError(RuntimeError):
 def __init__(self,message,*,code="UPGRADE_ERROR",recovery_point=None):super().__init__(message);self.code=code;self.recovery_point=recovery_point
@dataclass(frozen=True)
class Component:
 stack:str;name:str;service:str|None;container:str|None;compose:str|None;upstream:str|None;selectable:bool=True
def runtime_root():return Path(os.environ.get("LOCAL_AI_RUNTIME_ROOT","/opt/docker/runtime"))
def plan_path():return upgrade_plan.path(runtime_root())
def registry_cache_path():return upgrade_cache.path(runtime_root())
def registry_cache_ttl_seconds():return upgrade_cache.ttl_seconds()
def _load_registry_cache():return upgrade_cache.load(registry_cache_path())
def _save_registry_cache(entries):
 ordered=sorted(entries.items(),key=lambda item:float(item[1].get("stored_at",0)),reverse=True)[:REGISTRY_CACHE_MAX_ENTRIES];upgrade_cache.save(registry_cache_path(),dict(ordered))
def key(component):return f"{component.stack}/{component.name}"
def _registry_cache_key(component,image,local_digest):return upgrade_cache.key(key(component),image,local_digest)
def _cached_registry_state(component,image):
 ttl=registry_cache_ttl_seconds()
 if ttl<=0:return None
 local=upgrade_registry.local_digest(component.container,image) if component.container else None;entry=_load_registry_cache().get(_registry_cache_key(component,image,local))
 if not entry:return None
 stored_at,state=entry.get("stored_at"),entry.get("state")
 if not isinstance(stored_at,(int,float)) or time.time()-float(stored_at)>ttl or not isinstance(state,dict):return None
 try:return upgrade_registry.RegistryState(**state)
 except TypeError:return None
def _store_registry_state(component,image,state):
 if registry_cache_ttl_seconds()<=0:return
 entries=_load_registry_cache();entries[_registry_cache_key(component,image,state.local_digest)]={"stored_at":time.time(),"state":dict(state.__dict__)};_save_registry_cache(entries)
def load_catalog_raw():
 try:raw=component_inventory.compile_upgrade_catalog()
 except component_inventory.InventoryError as exc:raise UpgradeError(f"cannot compile component catalog: {exc}",code="UPGRADE_CATALOG_INVALID") from exc
 if raw.get("schema_version")!=1 or not isinstance(raw.get("stacks"),list):raise UpgradeError("unsupported component catalog schema",code="UPGRADE_CATALOG_INVALID")
 return raw
def component_records():return upgrade_catalog.records(load_catalog_raw())
def load_catalog():return upgrade_catalog.components(load_catalog_raw(),Component)
def read_env():return upgrade_runtime.read_env(ROOT)
def substitute_env(value,env):return upgrade_runtime.substitute_env(value,env)
def compose_image(component,env):return upgrade_runtime.compose_image(ROOT,component,env)
def running_image(component):return upgrade_runtime.running_image(ROOT,component)
def version_from_image(image):return upgrade_inventory.version_from_image(image)
def load_plan():
 try:return upgrade_plan.load(plan_path())
 except upgrade_plan.PlanError as exc:raise UpgradeError(str(exc),code="UPGRADE_PLAN_INVALID") from exc
def save_plan(plan):upgrade_plan.save(plan_path(),plan)
def _execution_metadata(record,component):return upgrade_inventory.execution_metadata(record,selectable=component.selectable)
def _registry_availability(component,image,*,online):
 if not online:return "unchecked",None,None
 try:
  state=_cached_registry_state(component,image) if image else None
  if state is None:
   state=upgrade_registry.inspect(component.container,image)
   if state is not None and image:_store_registry_state(component,image,state)
 except upgrade_registry.RegistryError as exc:raise UpgradeError(f"registry discovery failed for {key(component)}: {exc}",code="UPGRADE_REGISTRY_SOURCE_INVALID") from exc
 return upgrade_inventory.registry_state(state)
def _inventory_availability(component,record,observed_image,desired_image,*,query_upstream):
 actual=version_from_image(observed_image);availability=record.get("availability")
 if availability in ("local","n/a"):return availability,None,("local" if availability=="local" and observed_image else actual)
 available,registry,discovered=_registry_availability(component,observed_image or desired_image,online=query_upstream);display=upgrade_registry.display_label(observed_image,discovered_version=discovered) if observed_image else actual;return available,registry,display
def _selection_status(component_key,record,selection):
 try:return upgrade_policy.selection_status(runtime_root(),component_key,record,selection)
 except upgrade_policy.PolicyError as exc:raise UpgradeError(str(exc),code="UPGRADE_POLICY_INVALID") from exc
def inventory(*,query_upstream=True):
 env=read_env();selected=load_plan()["selected"];records=component_records();rows=[]
 for component in load_catalog():
  component_key=key(component);observed=running_image(component);record=records[component_key];selection=selected.get(component_key);available,registry,actual_display=_inventory_availability(component,record,observed,compose_image(component,env),query_upstream=query_upstream);actual=version_from_image(observed);policy_state=_selection_status(component_key,record,selection)
  rows.append({"stack":component.stack,"component":component.name,"actual":actual,"actual_display":actual_display,"current":actual,"current_display":actual_display,"available":available,"policy":policy_state["effective_policy"],"selectable":component.selectable,"execution":_execution_metadata(record,component),"selected":selection.get("version") if selection else None,"selection_valid":policy_state["selection_valid"],"registry":registry})
 return rows
def human_stack_id(stack):return upgrade_inventory.human_stack_id(stack)
def _human_available(row):return upgrade_inventory.human_available(row)
def print_table(rows):
 headers=("STACK","COMPONENT","INSTALLED","AVAILABLE","POLICY","SELECTABLE","SELECTED","VALID");values=[headers]
 for row in rows:
  valid=row["selection_valid"];values.append((human_stack_id(row["stack"]),row["component"],row.get("actual_display",row["actual"]),_human_available(row),row["policy"],"yes" if row["selectable"] else "no",row["selected"] or "-","-" if valid is None else ("yes" if valid else "no")))
 widths=[max(len(str(row[i])) for row in values) for i in range(len(headers))]
 for index,row in enumerate(values):
  print("  ".join(str(value).ljust(widths[i]) for i,value in enumerate(row)))
  if index==0:print("  ".join("-"*width for width in widths))
def find_component(stack,name):
 matches=[c for c in load_catalog() if c.stack==stack]
 if not matches:raise UpgradeError(f"unknown stack: {stack}",code="UPGRADE_STACK_UNKNOWN")
 if name is None:
  if len(matches)!=1:raise UpgradeError(f"{stack} has multiple components; specify one: "+", ".join(c.name for c in matches),code="UPGRADE_COMPONENT_REQUIRED")
  component=matches[0]
 else:
  component=next((c for c in matches if c.name==name),None)
  if component is None:raise UpgradeError(f"unknown component for {stack}: {name}",code="UPGRADE_COMPONENT_UNKNOWN")
 if not component.selectable:
  record=component_records()[key(component)];blocked_by=_execution_metadata(record,component)["blocked_by"];raise UpgradeError(f"component is inventory-only: {key(component)} ({blocked_by})",code="UPGRADE_COMPONENT_NOT_SELECTABLE")
 return component
