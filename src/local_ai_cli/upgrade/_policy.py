#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Package-private upgrade compatibility policy."""
from __future__ import annotations
import json,os,re
from pathlib import Path
POLICIES=("minor-series","major-series","manual");SCHEMA_VERSION=1;_VERSION_RE=re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?(?:[-+].*)?$")
class PolicyError(RuntimeError):pass
def policy_path(runtime_root:Path)->Path:return runtime_root/"platform"/"upgrade-policy.json"
def _load_state(runtime_root:Path)->dict:
 path=policy_path(runtime_root)
 if not path.is_file():return {"schema_version":SCHEMA_VERSION,"overrides":{},"selectable_overrides":{}}
 try:payload=json.loads(path.read_text(encoding="utf-8"))
 except (OSError,json.JSONDecodeError) as exc:raise PolicyError(f"cannot read upgrade policy state: {exc}") from exc
 if payload.get("schema_version")!=SCHEMA_VERSION or not isinstance(payload.get("overrides"),dict):raise PolicyError("unsupported upgrade policy state schema")
 if not isinstance(payload.get("selectable_overrides",{}),dict):raise PolicyError("unsupported upgrade policy state schema")
 return payload
def _save_state(runtime_root:Path,state:dict)->None:
 path=policy_path(runtime_root);path.parent.mkdir(parents=True,exist_ok=True)
 payload={"schema_version":SCHEMA_VERSION,"overrides":dict(sorted(state.get("overrides",{}).items())),"selectable_overrides":dict(sorted(state.get("selectable_overrides",{}).items()))}
 tmp=path.with_suffix(".tmp");tmp.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8");os.replace(tmp,path)
def load_overrides(runtime_root:Path)->dict[str,str]:
 overrides={}
 for component_key,value in _load_state(runtime_root).get("overrides",{}).items():
  if value not in POLICIES:raise PolicyError(f"invalid policy override for {component_key}: {value}")
  overrides[str(component_key)]=str(value)
 return overrides
def set_override(runtime_root:Path,component_key:str,policy:str)->None:
 if policy not in POLICIES:raise PolicyError(f"unsupported upgrade policy: {policy}")
 state=_load_state(runtime_root);state["overrides"][component_key]=policy;_save_state(runtime_root,state)
def clear_override(runtime_root:Path,component_key:str)->None:
 state=_load_state(runtime_root);state["overrides"].pop(component_key,None);_save_state(runtime_root,state)
def load_selectable_overrides(runtime_root:Path)->dict[str,bool]:
 overrides={}
 for component_key,value in _load_state(runtime_root).get("selectable_overrides",{}).items():
  if not isinstance(value,bool):raise PolicyError(f"invalid selectable override for {component_key}: {value}")
  overrides[str(component_key)]=value
 return overrides
def set_selectable_override(runtime_root:Path,component_key:str,selectable:bool)->None:
 state=_load_state(runtime_root);state["selectable_overrides"][component_key]=bool(selectable);_save_state(runtime_root,state)
def clear_selectable_override(runtime_root:Path,component_key:str)->None:
 state=_load_state(runtime_root);state["selectable_overrides"].pop(component_key,None);_save_state(runtime_root,state)
def effective_selectable(runtime_root:Path,component_key:str,manifest_default:bool)->tuple[bool,bool|None,bool]:
 override=load_selectable_overrides(runtime_root).get(component_key);return bool(manifest_default),override,override if override is not None else bool(manifest_default)
def default_policy(component:dict)->str:
 value=component.get("default_policy","manual")
 if value not in POLICIES:raise PolicyError(f"invalid default policy for {component.get('stack')}/{component.get('id')}: {value}")
 return value
def effective_policy(runtime_root:Path,component_key:str,component:dict)->tuple[str,str|None,str]:
 default=default_policy(component);override=load_overrides(runtime_root).get(component_key);return default,override,override or default
def version_tuple(value:str)->tuple[int,int,int]|None:
 match=_VERSION_RE.fullmatch(value)
 if not match:return None
 return int(match.group(1)),int(match.group(2)),int(match.group(3) or 0)
def target_is_newer(current:str,target:str)->bool|None:
 a=version_tuple(current);b=version_tuple(target)
 if a is None or b is None:return None
 return b>a
def target_supported(policy:str,current:str,target:str)->bool:
 if current==target:return False
 a=version_tuple(current);b=version_tuple(target)
 if policy=="manual":return b>a if a is not None and b is not None else True
 if a is None or b is None or b<=a:return False
 if policy=="minor-series":return b[:2]==a[:2]
 if policy=="major-series":return b[0]==a[0]
 raise PolicyError(f"unsupported upgrade policy: {policy}")
def selection_status(runtime_root:Path,component_key:str,component:dict,selection:dict|None)->dict:
 default,override,effective=effective_policy(runtime_root,component_key,component);result={"default_policy":default,"override_policy":override,"effective_policy":effective,"selection_valid":None}
 if selection:
  current=selection.get("current_at_selection");target=selection.get("version");accepted=effective_selectable(runtime_root,component_key,component.get("selectable",True))[2];result["selection_valid"]=bool(isinstance(current,str) and isinstance(target,str) and accepted and target_supported(effective,current,target))
 return result
