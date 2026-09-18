# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Selection and stale-plan validation for guarded component upgrades."""
from __future__ import annotations
from . import core as upgrade
from . import policy as upgrade_policy
from . import registry as upgrade_registry
def component_record(component):return upgrade.component_records()[upgrade.key(component)]
def effective_policy(component):
 try:return upgrade_policy.effective_policy(upgrade.runtime_root(),upgrade.key(component),component_record(component))
 except upgrade_policy.PolicyError as exc:raise upgrade.UpgradeError(str(exc),code="UPGRADE_POLICY_INVALID") from exc
def resolve_component(stack,name):
 matches=[c for c in upgrade.load_catalog() if c.stack==stack]
 if not matches:raise upgrade.UpgradeError(f"unknown stack: {stack}",code="UPGRADE_STACK_UNKNOWN")
 if name is None:
  if len(matches)!=1:raise upgrade.UpgradeError(f"{stack} has multiple components; specify one: "+", ".join(c.name for c in matches),code="UPGRADE_COMPONENT_REQUIRED")
  return matches[0]
 component=next((c for c in matches if c.name==name),None)
 if component is None:raise upgrade.UpgradeError(f"unknown component for {stack}: {name}",code="UPGRADE_COMPONENT_UNKNOWN")
 return component
def apply_recipe_available(record):
 apply=record.get("apply") or {};return apply.get("type")=="env-version" and all(isinstance(apply.get(k),str) and bool(apply.get(k)) for k in ("env_key","image_env_key")) and isinstance(apply.get("deploy"),list) and bool(apply.get("deploy"))
def effective_selectable(component):
 return upgrade_policy.effective_selectable(upgrade.runtime_root(),upgrade.key(component),component.selectable)
def require_selection_permission(component):
 if effective_selectable(component)[2]:return
 record=component_record(component);blocked=(record.get("execution") or {}).get("blocked_by")
 raise upgrade.UpgradeError(f"component is not selectable: {upgrade.key(component)} ({blocked}); enable it with 'upgrade selectable {upgrade.human_stack_id(component.stack)} {component.name} enable --yes'",code="UPGRADE_COMPONENT_NOT_SELECTABLE")
def current_runtime_version(component,env):
 running=upgrade.running_image(component)
 if running:
  literal=upgrade.version_from_image(running)
  if component.container:
   try:state=upgrade_registry.inspect(component.container,running)
   except upgrade_registry.RegistryError:state=None
   if state is not None and state.current_version:return state.current_version
  return literal
 return upgrade.version_from_image(upgrade.compose_image(component,env))
def target_reference(component,version,env):
 image=upgrade.running_image(component) or upgrade.compose_image(component,env)
 if not image:raise upgrade.UpgradeError(f"cannot determine image repository for {upgrade.key(component)}",code="UPGRADE_TARGET_NOT_AVAILABLE")
 return upgrade_registry.parse_reference(image).with_tag(version)
def validate_target(component,current,version,env):
 target_ref=target_reference(component,version,env);probe=upgrade_registry.manifest_probe(target_ref)
 if probe.status!="ok" or not probe.digest:raise upgrade.UpgradeError(f"target image is not available for {upgrade.key(component)}: {target_ref} ({probe.status})",code="UPGRADE_TARGET_NOT_AVAILABLE")
 effective=effective_policy(component)[2]
 if not upgrade_policy.target_supported(effective,current,version):
  if upgrade_policy.target_is_newer(current,version) is False:raise upgrade.UpgradeError(f"upgrade target is not newer for {upgrade.key(component)}: {current} -> {version}",code="UPGRADE_TARGET_NOT_NEWER")
  raise upgrade.UpgradeError(f"target {version} is outside {effective} policy for {upgrade.key(component)}",code="UPGRADE_TARGET_UNSUPPORTED")
 return effective,target_ref,probe.digest
def validate_immutable_target(component,selection,env):
 target,stored_ref,stored_digest=selection.get("version"),selection.get("target_image"),selection.get("target_digest")
 if not all(isinstance(v,str) and v for v in (target,stored_ref,stored_digest)):raise upgrade.UpgradeError(f"upgrade selection predates immutable target identity for {upgrade.key(component)}; reselect the target",code="UPGRADE_PLAN_STALE")
 target_ref=target_reference(component,target,env)
 if target_ref!=stored_ref:raise upgrade.UpgradeError(f"target image reference changed for {upgrade.key(component)}: selected {stored_ref}, now {target_ref}",code="UPGRADE_PLAN_STALE")
 probe=upgrade_registry.manifest_probe(target_ref)
 if probe.status!="ok" or not probe.digest:raise upgrade.UpgradeError(f"selected target is no longer available for {upgrade.key(component)}: {target_ref} ({probe.status})",code="UPGRADE_TARGET_NOT_AVAILABLE")
 if probe.digest!=stored_digest:raise upgrade.UpgradeError(f"selected target tag moved for {upgrade.key(component)}: {stored_digest} -> {probe.digest}",code="UPGRADE_TARGET_MOVED")
def validate_selected_baselines(selections):
 components={upgrade.key(c):c for c in upgrade.load_catalog()};records=upgrade.component_records();env=upgrade.read_env()
 for selection in selections:
  component_key=f"{selection.get('stack')}/{selection.get('component')}";component=components.get(component_key)
  if component is None:raise upgrade.UpgradeError(f"selected component no longer exists: {component_key}",code="UPGRADE_PLAN_STALE")
  if not effective_selectable(component)[2]:raise upgrade.UpgradeError(f"selected component is no longer selectable: {component_key}",code="UPGRADE_COMPONENT_NOT_SELECTABLE")
  current=current_runtime_version(component,env);expected=selection.get("current_at_selection")
  if current!=expected:raise upgrade.UpgradeError(f"upgrade plan is stale for {component_key}: selected from {expected}, current is {current}",code="UPGRADE_PLAN_STALE")
  target=selection.get("version")
  if target==current:raise upgrade.UpgradeError(f"upgrade target is already current for {component_key}: {current}",code="UPGRADE_PLAN_STALE")
  try:effective=upgrade_policy.effective_policy(upgrade.runtime_root(),component_key,records[component_key])[2]
  except upgrade_policy.PolicyError as exc:raise upgrade.UpgradeError(str(exc),code="UPGRADE_POLICY_INVALID") from exc
  if not isinstance(target,str) or not upgrade_policy.target_supported(effective,current,target):raise upgrade.UpgradeError(f"selected target {target} is no longer permitted by {effective} policy for {component_key}",code="UPGRADE_TARGET_UNSUPPORTED")
  validate_immutable_target(component,selection,env)
def execution_records_for(selections):
 records=upgrade.component_records();result={key:dict(value) for key,value in records.items()}
 for selection in selections:
  component_key=f"{selection['stack']}/{selection['component']}"
  if component_key in result:
   record=dict(result[component_key]);_,_,effective=upgrade_policy.effective_selectable(upgrade.runtime_root(),component_key,record.get("selectable",True));record["selectable"]=effective;result[component_key]=record
 return result
