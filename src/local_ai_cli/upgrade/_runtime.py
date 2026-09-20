#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Package-private runtime and Compose image discovery."""
from __future__ import annotations
import re,subprocess
from pathlib import Path
from typing import Protocol
class ComponentLike(Protocol):
 service:str|None;container:str|None;compose:str|None
_ENV_REFERENCE=re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::[-?]([^}]*))?\}");_SERVICE=re.compile(r"^  ([A-Za-z0-9_.-]+):\s*$");_IMAGE=re.compile(r"^    image:\s*(.+?)\s*$")
def read_env(root:Path)->dict[str,str]:
 path=root/".env"
 if not path.is_file():path=root/".env.template"
 result={}
 for raw in path.read_text(encoding="utf-8").splitlines():
  line=raw.strip()
  if not line or line.startswith("#") or "=" not in line:continue
  key,value=line.split("=",1);result[key.strip()]=value.strip().strip('"').strip("'")
 return result
def substitute_env(value:str,env:dict[str,str])->str:
 def replace(match):
  key,default=match.group(1),match.group(2);return env.get(key) or (default or match.group(0))
 return _ENV_REFERENCE.sub(replace,value)
def compose_image(root:Path,component:ComponentLike,env:dict[str,str])->str|None:
 if not component.compose or not component.service:return None
 path=root/component.compose
 if not path.is_file():return None
 current=None
 for raw in path.read_text(encoding="utf-8").splitlines():
  m=_SERVICE.match(raw)
  if m:current=m.group(1);continue
  if current!=component.service:continue
  m=_IMAGE.match(raw)
  if m:return substitute_env(m.group(1).strip('"').strip("'"),env)
 return None
def running_container_image(root:Path,container:str|None)->str|None:
 if not container:return None
 try:r=subprocess.run(["docker","inspect","-f","{{.Config.Image}}",container],cwd=root,text=True,capture_output=True,check=False)
 except OSError:return None
 return None if r.returncode!=0 else (r.stdout.strip() or None)
def running_image(root:Path,component:ComponentLike)->str|None:return running_container_image(root,component.container)
