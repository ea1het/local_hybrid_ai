# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Serialize destructive upgrade application and journal failed attempts."""
from __future__ import annotations
import contextlib,fcntl,io,json,os,re,sys
from datetime import datetime,timezone
from pathlib import Path
from typing import Callable

def _runtime_root():return Path(os.environ.get("LOCAL_AI_RUNTIME_ROOT","/opt/docker/runtime"))
def _is_upgrade_apply(argv):
 semantic=[arg for arg in argv if arg not in {"--json","--yes"}]
 return semantic==["upgrade"] and "--yes" in argv
def _selected_snapshot(runtime_root):
 path=runtime_root/"platform"/"upgrade-plan.json"
 try:
  payload=json.loads(path.read_text(encoding="utf-8"));selected=payload.get("selected",{})
  if isinstance(selected,dict):return [dict(value) for _,value in sorted(selected.items()) if isinstance(value,dict)]
 except (OSError,json.JSONDecodeError):pass
 return []
def _error_code(stdout,stderr,*,json_output):
 if json_output:
  try:
   code=json.loads(stdout).get("error",{}).get("code")
   if isinstance(code,str) and code:return code
  except (json.JSONDecodeError,AttributeError):pass
 match=re.search(r"UPGRADE ERROR \[([^]]+)\]",stderr);return match.group(1) if match else "UPGRADE_FAILED"
def _recovery_point(stdout):
 try:
  value=json.loads(stdout).get("recovery_point");return value if isinstance(value,str) and value else None
 except (json.JSONDecodeError,AttributeError):return None
def _journal_failure(runtime_root,*,selections,code,recovery_point):
 platform=runtime_root/"platform";platform.mkdir(parents=True,exist_ok=True);event={"schema_version":1,"timestamp":datetime.now(timezone.utc).isoformat(),"success":False,"command":"upgrade.apply","stage":"apply","error_code":code,"recovery_point":recovery_point,"selected":selections}
 with (platform/"upgrade-history.jsonl").open("a",encoding="utf-8") as handle:handle.write(json.dumps(event,sort_keys=True)+"\n")
def run_guarded(argv:list[str],main:Callable[[],int])->int:
 if not _is_upgrade_apply(argv):return main()
 runtime_root=_runtime_root();platform=runtime_root/"platform";platform.mkdir(parents=True,exist_ok=True);lock_path=platform/"upgrade.lock";json_output="--json" in argv
 with lock_path.open("a+") as lock_handle:
  try:fcntl.flock(lock_handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:
   if json_output:print(json.dumps({"schema_version":"1","success":False,"error":{"code":"UPGRADE_BUSY","message":"another upgrade execution is already in progress"}},indent=2,sort_keys=True))
   else:print("UPGRADE ERROR [UPGRADE_BUSY]: another upgrade execution is already in progress",file=sys.stderr)
   return 1
  selections=_selected_snapshot(runtime_root);stdout_buffer=io.StringIO();stderr_buffer=io.StringIO()
  try:
   with contextlib.redirect_stdout(stdout_buffer),contextlib.redirect_stderr(stderr_buffer):rc=main()
  finally:fcntl.flock(lock_handle.fileno(),fcntl.LOCK_UN)
  stdout=stdout_buffer.getvalue();stderr=stderr_buffer.getvalue()
  if stdout:print(stdout,end="")
  if stderr:print(stderr,end="",file=sys.stderr)
  if rc!=0:_journal_failure(runtime_root,selections=selections,code=_error_code(stdout,stderr,json_output=json_output),recovery_point=_recovery_point(stdout))
  return rc
