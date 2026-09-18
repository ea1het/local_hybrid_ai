# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Structured upgrade orchestration. Global CLI options belong to ./local-ai."""
from __future__ import annotations
import json
from . import core as upgrade
from . import executor as upgrade_executor
from . import policy as upgrade_policy
from . import selection as upgrade_selection
_component_record=upgrade_selection.component_record;_effective_policy=upgrade_selection.effective_policy;_resolve_component=upgrade_selection.resolve_component;_current_runtime_version=upgrade_selection.current_runtime_version;_validate_target=upgrade_selection.validate_target;validate_selected_baselines=upgrade_selection.validate_selected_baselines;_execution_records_for=upgrade_selection.execution_records_for
def _require_selection_permission(component):return upgrade_selection.require_selection_permission(component)
def select_payload(stack,component_name,version):
 component=_resolve_component(stack,component_name);_require_selection_permission(component);env=upgrade.read_env();current=_current_runtime_version(component,env)
 if current==version:raise upgrade.UpgradeError(f"{component.stack}/{component.name} is already at {version}",code="UPGRADE_ALREADY_CURRENT")
 effective,target_ref,target_digest=_validate_target(component,current,version,env);plan=upgrade.load_plan();selection={"stack":component.stack,"component":component.name,"current_at_selection":current,"version":version,"policy_at_selection":effective,"target_image":target_ref,"target_digest":target_digest}
 plan["selected"][upgrade.key(component)]=selection;upgrade.save_plan(plan);return {"schema_version":upgrade.SCHEMA_VERSION,"command":"upgrade.select","success":True,"selection":selection}
def clear_payload(stack,component_name):
 component=_resolve_component(stack,component_name);plan=upgrade.load_plan();plan["selected"].pop(upgrade.key(component),None);upgrade.save_plan(plan);return {"schema_version":upgrade.SCHEMA_VERSION,"command":"upgrade.clear","success":True,"stack":component.stack,"component":component.name}
def selected_records():return [dict(v) for _,v in sorted(upgrade.load_plan()["selected"].items())]
def execute_payload():
 selections=selected_records()
 if not selections:raise upgrade.UpgradeError("no upgrades are selected",code="UPGRADE_NOTHING_SELECTED")
 validate_selected_baselines(selections)
 try:result=upgrade_executor.execute(root=upgrade.ROOT,runtime_root=upgrade.runtime_root(),selections=selections,components=_execution_records_for(selections),plan_path=upgrade.plan_path(),quiet=True)
 except upgrade_executor.UpgradeExecutionError as exc:raise upgrade.UpgradeError(str(exc),code=exc.code,recovery_point=exc.recovery_point) from exc
 return {"schema_version":upgrade.SCHEMA_VERSION,"command":"upgrade.apply","success":True,"recovery_point":result.get("recovery_point"),"upgraded":result.get("upgraded",[]),"reverified_stacks":[f"stack{sid}" for sid in result.get("reverified_stacks",[])]}
def json_payload(rows):return {"schema_version":upgrade.SCHEMA_VERSION,"command":"upgrade.check","success":True,"components":rows}
def _policy_record(stack,component_name):
 records=upgrade.component_records();matches=[(k,v) for k,v in records.items() if v.get("stack")==stack]
 if not matches:raise upgrade.UpgradeError(f"unknown stack: {stack}",code="UPGRADE_STACK_UNKNOWN")
 if component_name is None:
  if len(matches)!=1:raise upgrade.UpgradeError(f"{stack} has multiple components; specify one: "+", ".join(v["id"] for _,v in matches),code="UPGRADE_COMPONENT_REQUIRED")
  return matches[0]
 for key,record in matches:
  if record.get("id")==component_name:return key,record
 raise upgrade.UpgradeError(f"unknown component for {stack}: {component_name}",code="UPGRADE_COMPONENT_UNKNOWN")
def _policy_row(key,record,plan):
 try:state=upgrade_policy.selection_status(upgrade.runtime_root(),key,record,plan["selected"].get(key))
 except upgrade_policy.PolicyError as exc:raise upgrade.UpgradeError(str(exc),code="UPGRADE_POLICY_INVALID") from exc
 effective=upgrade_policy.effective_selectable(upgrade.runtime_root(),key,record.get("selectable",True))[2];return {"stack":record["stack"],"component":record["id"],**state,"selectable":effective,"selected":plan["selected"].get(key,{}).get("version")}
def _selectable_row(key,record):
 default,override,effective=upgrade_policy.effective_selectable(upgrade.runtime_root(),key,record.get("selectable",True))
 return {"stack":record["stack"],"component":record["id"],"default_selectable":default,"override_selectable":override,"effective_selectable":effective,"executable":upgrade_selection.apply_recipe_available(record)}
def selectable_payload(args):
 records=upgrade.component_records()
 if not args:return {"schema_version":upgrade.SCHEMA_VERSION,"command":"upgrade.selectable","success":True,"components":[_selectable_row(k,r) for k,r in sorted(records.items())]}
 action=None;left=list(args)
 if left[-1:]==["enable"]:action,left="enable",left[:-1]
 elif left[-1:]==["disable"]:action,left="disable",left[:-1]
 elif left[-1:]==["clear"]:action,left="clear",left[:-1]
 if len(left) not in (1,2):raise upgrade.UpgradeError("invalid selectable syntax",code="UPGRADE_USAGE")
 key,record=_policy_record(left[0],left[1] if len(left)==2 else None);before=_selectable_row(key,record)
 if action=="enable":upgrade_policy.set_selectable_override(upgrade.runtime_root(),key,True)
 elif action=="disable":upgrade_policy.set_selectable_override(upgrade.runtime_root(),key,False)
 elif action=="clear":upgrade_policy.clear_selectable_override(upgrade.runtime_root(),key)
 after=_selectable_row(key,record);payload={"schema_version":upgrade.SCHEMA_VERSION,"command":"upgrade.selectable","success":True,"action":action or "show",**after}
 if action:payload["previous_effective_selectable"]=before["effective_selectable"]
 return payload
def policy_payload(args):
 records=upgrade.component_records();plan=upgrade.load_plan()
 if not args:return {"schema_version":upgrade.SCHEMA_VERSION,"command":"upgrade.policy","success":True,"components":[_policy_row(k,r,plan) for k,r in sorted(records.items())]}
 action=policy=None;left=list(args)
 if "set" in left:
  pos=left.index("set");target,right=left[:pos],left[pos+1:]
  if len(right)!=1:raise upgrade.UpgradeError("invalid policy set syntax",code="UPGRADE_USAGE")
  action,policy,left="set",right[0],target
 elif left[-1:]==["clear"]:action,left="clear",left[:-1]
 if len(left) not in (1,2):raise upgrade.UpgradeError("invalid policy syntax",code="UPGRADE_USAGE")
 key,record=_policy_record(left[0],left[1] if len(left)==2 else None);before=_policy_row(key,record,plan)
 if action=="set":
  if policy not in upgrade_policy.POLICIES:raise upgrade.UpgradeError(f"unsupported upgrade policy: {policy}",code="UPGRADE_POLICY_INVALID")
  upgrade_policy.set_override(upgrade.runtime_root(),key,policy)
 elif action=="clear":upgrade_policy.clear_override(upgrade.runtime_root(),key)
 after=_policy_row(key,record,plan);payload={"schema_version":upgrade.SCHEMA_VERSION,"command":"upgrade.policy","success":True,"action":action or "show",**after}
 if action:payload["previous_effective_policy"]=before["effective_policy"]
 return payload
def cli_text(payload):
 command=payload.get("command")
 if not payload.get("success"):return f"UPGRADE ERROR [{payload['error']['code']}]: {payload['error']['message']}"
 if command=="upgrade.check":
  rows=payload.get("components",[]);headers=("STACK","COMPONENT","CURRENT","AVAILABLE","POLICY","DRIFT");values=[headers]
  for row in rows:values.append((upgrade.human_stack_id(row.get("stack","")),row.get("component","-"),row.get("current") or "-",row.get("available") or "-",row.get("effective_policy") or row.get("policy") or "-",row.get("drift") or "-"))
  widths=[max(len(str(r[i])) for r in values) for i in range(len(headers))];lines=[]
  for idx,row in enumerate(values):lines.append("  ".join(str(v).ljust(widths[i]) for i,v in enumerate(row)));lines.extend(["  ".join("-"*w for w in widths)] if idx==0 else [])
  return "\n".join(lines)
 if command=="upgrade.select":
  s=payload["selection"];return f"Selected {s['stack']}/{s['component']}: {s['current_at_selection']} -> {s['version']} ({s['policy_at_selection']}, {s['target_digest']})"
 if command=="upgrade.clear":return f"Cleared {payload['stack']}/{payload['component']}"
 if command=="upgrade.apply":
  lines=["UPGRADE: PASS"]
  if payload.get("recovery_point"):lines.append(f"- recovery point: {payload['recovery_point']}")
  for item in payload["upgraded"]:lines.append(f"- {item['stack']}/{item['component']}: {item['current_at_selection']} -> {item['version']}")
  if payload["reverified_stacks"]:lines.append("- reverified consumers: "+", ".join(payload["reverified_stacks"]))
  return "\n".join(lines)
 if command=="upgrade.policy":
  rows=payload.get("components") or [payload];headers=("STACK","COMPONENT","DEFAULT","OVERRIDE","EFFECTIVE","SELECTABLE","SELECTED","VALID");values=[headers]
  for row in rows:
   valid=row["selection_valid"];values.append((upgrade.human_stack_id(row["stack"]),row["component"],row["default_policy"],row["override_policy"] or "-",row["effective_policy"],"yes" if row["selectable"] else "no",row["selected"] or "-","-" if valid is None else ("yes" if valid else "no")))
  widths=[max(len(str(r[i])) for r in values) for i in range(len(headers))];lines=[]
  for idx,row in enumerate(values):lines.append("  ".join(str(v).ljust(widths[i]) for i,v in enumerate(row)));lines.extend(["  ".join("-"*w for w in widths)] if idx==0 else [])
  return "\n".join(lines)
 if command=="upgrade.selectable":
  rows=payload.get("components") or [payload];headers=("STACK","COMPONENT","DEFAULT","OVERRIDE","EFFECTIVE","EXECUTABLE");values=[headers]
  for row in rows:
   values.append((upgrade.human_stack_id(row["stack"]),row["component"],"yes" if row["default_selectable"] else "no","-" if row["override_selectable"] is None else ("yes" if row["override_selectable"] else "no"),"yes" if row["effective_selectable"] else "no","yes" if row["executable"] else "no"))
  widths=[max(len(str(r[i])) for r in values) for i in range(len(headers))];lines=[]
  for idx,row in enumerate(values):lines.append("  ".join(str(v).ljust(widths[i]) for i,v in enumerate(row)));lines.extend(["  ".join("-"*w for w in widths)] if idx==0 else [])
  return "\n".join(lines)
 return ""
def error_payload(exc):
 payload={"schema_version":upgrade.SCHEMA_VERSION,"success":False,"error":{"code":exc.code,"message":str(exc)}}
 if exc.recovery_point:payload["recovery_point"]=exc.recovery_point
 return payload
def build_payload(args,*,apply_selected=False):
 try:
  if apply_selected:
   if args:raise upgrade.UpgradeError("invalid upgrade syntax",code="UPGRADE_USAGE")
   return execute_payload(),0
  if not args or args==["check"]:return json_payload(upgrade.inventory(query_upstream=True)),0
  if args in (["--offline"],["check","--offline"],["--offline","check"]):return json_payload(upgrade.inventory(query_upstream=False)),0
  if args and args[0]=="policy":return policy_payload(args[1:]),0
  if args and args[0]=="selectable":return selectable_payload(args[1:]),0
  if "select" in args:
   pos=args.index("select");left,right=args[:pos],args[pos+1:]
   if len(right)!=1 or len(left) not in (1,2):raise upgrade.UpgradeError("invalid select syntax",code="UPGRADE_USAGE")
   return select_payload(left[0],left[1] if len(left)==2 else None,right[0]),0
  if args[-1:]==["clear"] and len(args) in (2,3):left=args[:-1];return clear_payload(left[0],left[1] if len(left)==2 else None),0
  raise upgrade.UpgradeError("invalid upgrade syntax",code="UPGRADE_USAGE")
 except (upgrade.UpgradeError,upgrade_policy.PolicyError,OSError,json.JSONDecodeError) as exc:
  if isinstance(exc,upgrade_policy.PolicyError):exc=upgrade.UpgradeError(str(exc),code="UPGRADE_POLICY_INVALID")
  elif not isinstance(exc,upgrade.UpgradeError):exc=upgrade.UpgradeError(str(exc))
  return error_payload(exc),1
