#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Importable engine for resuming a reconstructed clean-target restore."""
from __future__ import annotations
import hashlib,os,sqlite3,subprocess
from dataclasses import dataclass
from pathlib import Path
import _planner as planner,_restore_all as restore_all,_restore_compat as restore_compat,_restore_live as restore_live,_stack4_restore_verify as stack4_restore_verify
class ResumeError(RuntimeError): pass
@dataclass(frozen=True)
class ResumeContext:
 backup_set:Path;bootstrap:Path;source_commit:str;resolved_stacks:tuple[int,...];env_artifact:Path;values:dict[str,str];stacks_root:Path;base_path:Path
def sha256(path):
 h=hashlib.sha256()
 with path.open("rb") as f:
  for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
 return h.hexdigest()
def run(cmd,*,cwd=None):return subprocess.run(cmd,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,check=False)
def require_ok(cp,label):
 if cp.returncode!=0:
  detail=(cp.stderr or cp.stdout or "").strip();detail=("..."+detail[-2000:]) if len(detail)>2000 else detail
  raise ResumeError(f"{label} failed: {detail or 'no diagnostic output'}")
 return cp.stdout.strip()
def read_env_artifact(backup_set):
 metadata=restore_all.read_completed_backup_set(backup_set);matches=[a for a in metadata.get("global_artifacts",[]) if a.get("resource_id")=="operational-env"]
 if len(matches)!=1:raise ResumeError("backup set must contain exactly one operational-env global artifact")
 env_path=backup_set/matches[0]["relative_path"]
 if not env_path.is_file() or env_path.is_symlink():raise ResumeError("operational environment artifact is missing or invalid")
 return env_path,planner.read_dotenv_presence(env_path)
def _recorded_installer_path(source_commit):
 for candidate in ("commands/install.py","installer/install.py","install.py"):
  if subprocess.run(["git","cat-file","-e",f"{source_commit}:{candidate}"],cwd=restore_all.PROJECT_ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False).returncode==0:return candidate
 raise ResumeError("recorded source contains no supported installer engine")
def verify_source(backup_set,stacks_root,source_commit):
 relative=_recorded_installer_path(source_commit);target=stacks_root/relative
 if not target.is_file() or target.is_symlink():raise ResumeError(f"restored source is incomplete: {relative} missing")
 cp=subprocess.run(["git","show",f"{source_commit}:{relative}"],cwd=restore_all.PROJECT_ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
 if cp.returncode!=0:raise ResumeError("recorded source lookup failed")
 if hashlib.sha256(target.read_bytes()).digest()!=hashlib.sha256(cp.stdout).digest():raise ResumeError("restored source no longer matches backup source commit")
def verify_env(env_artifact,stacks_root):
 target=stacks_root/".env"
 if not target.is_file() or target.is_symlink():raise ResumeError("restored operational .env missing")
 if sha256(target)!=sha256(env_artifact):raise ResumeError("restored operational .env differs from recovery point")
 if target.stat().st_mode&0o777!=0o600:raise ResumeError("restored operational .env mode is not 0600")
def verify_prepared(stacks_root,resolved):
 for sid in resolved:
  if len(list(stacks_root.glob(f"stack{sid}_-*/.lock")))!=1:raise ResumeError(f"stack{sid} is not unambiguously PREPARED")
def postgres_table_count(values):
 db=planner.require_env_value(values,"LITELLM_DB_NAME",label="LITELLM_DB_NAME");text=require_ok(run(["docker","exec","litellm-postgres","psql","-At","-U","postgres","-d",db,"-c","SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema');"]),"LiteLLM PostgreSQL verification")
 try:count=int(text)
 except ValueError as exc:raise ResumeError("invalid LiteLLM PostgreSQL table count") from exc
 if count<=0:raise ResumeError("LiteLLM PostgreSQL restored state is empty")
 return count
def gitea_state(base_path):
 db=base_path/"service_-_gitea"/"data"/"gitea.db"
 if not db.is_file() or db.is_symlink():raise ResumeError("restored Gitea SQLite database missing")
 con=sqlite3.connect(f"file:{db}?mode=ro",uri=True)
 try:tables=int(con.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0])
 finally:con.close()
 repos=stack4_restore_verify.find_bare_repositories(base_path/"service_-_gitea"/"data"/"git"/"repositories")
 for repo in repos:stack4_restore_verify.verify_repository(repo)
 if tables<=0 or not repos:raise ResumeError("restored Gitea durable state is incomplete")
 return tables,len(repos)
def verify_memory(base_path,values):
 service=planner.require_env_value(values,"HERMES_MEMORY_SERVICE",label="HERMES_MEMORY_SERVICE");branch=planner.require_env_value(values,"GITMEM_BRANCH",label="GITMEM_BRANCH");repo=base_path/service/"data";prefix=["git","-c",f"safe.directory={repo}","-C",str(repo)]
 head=require_ok(run(prefix+["rev-parse","HEAD"]),"portable memory HEAD")
 if require_ok(run(prefix+["status","--porcelain"]),"portable memory status"):raise ResumeError("portable memory working tree is not clean")
 if require_ok(run(prefix+["rev-parse",f"refs/remotes/origin/{branch}"]),"portable memory remote tracking HEAD")!=head:raise ResumeError("portable memory is not aligned with remote tracking branch")
 return head
def verify_bootstrap(source,base_path,values):
 target=base_path/planner.require_env_value(values,"MEMORY_SYNC_SERVICE",label="MEMORY_SYNC_SERVICE")/"ssh"
 for name in ("ssh_config","id_ed25519","known_hosts"):
  src=source/name;dst=target/name
  if not src.is_file() or src.is_symlink() or not dst.is_file() or dst.is_symlink():raise ResumeError(f"memory-sync SSH material missing: {name}")
  if sha256(src)!=sha256(dst):raise ResumeError(f"memory-sync SSH material differs from bootstrap: {name}")
def persist_git_memory_intent(base_path,values):
 service=planner.require_env_value(values,"MEMORY_SYNC_SERVICE",label="MEMORY_SYNC_SERVICE")
 try:uid=int(planner.require_env_value(values,"HERMES_UID",label="HERMES_UID"));gid=int(planner.require_env_value(values,"HERMES_GID",label="HERMES_GID"))
 except ValueError as exc:raise ResumeError("invalid HERMES_UID/HERMES_GID for Git-memory desired state") from exc
 if uid<0 or gid<0:raise ResumeError("invalid negative HERMES_UID/HERMES_GID")
 root=base_path/service
 if root.is_symlink():raise ResumeError("memory-sync runtime root must not be a symlink")
 root.mkdir(parents=True,exist_ok=True);target=root/"desired-state"
 if target.exists() and target.is_symlink():raise ResumeError("Git-memory desired-state must not be a symlink")
 temp=root/f".desired-state.restore-{os.getpid()}"
 try:
  fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o640)
  try:
   with os.fdopen(fd,"w",encoding="utf-8") as handle:handle.write("enabled\n");handle.flush();os.fsync(handle.fileno())
   os.chown(temp,uid,gid);os.chmod(temp,0o640);os.replace(temp,target)
  finally:
   if temp.exists():temp.unlink()
 except OSError as exc:raise ResumeError(f"cannot persist Git-memory desired state: {exc}") from exc
 if target.read_text(encoding="utf-8")!="enabled\n" or target.stat().st_mode&0o777!=0o640:raise ResumeError("Git-memory desired-state verification failed")
def enable_memory_sync(stacks_root,base_path,values):
 persist_git_memory_intent(base_path,values);container=planner.require_env_value(values,"MEMORY_SYNC_CONTAINER",label="MEMORY_SYNC_CONTAINER");cp=run(["docker","compose","--profile","git-memory","up","-d","--build","hermes-memory-sync"],cwd=stacks_root/"stack6_-_hermes");require_ok(cp,"Stack6 memory-sync profile restore");restore_compat.wait_required_runtime(stacks_root,[6],timeout=240)
 if require_ok(run(["docker","inspect","-f","{{.State.Running}}",container]),"memory-sync container status")!="true":raise ResumeError("memory-sync container is not running")
def _prepare_resume_context(backup_set,bootstrap):
 plan=restore_all.plan_restore_all(backup_set);env_artifact,values=read_env_artifact(backup_set);return ResumeContext(backup_set,bootstrap,plan.source_commit,tuple(plan.resolved_stacks),env_artifact,values,restore_live._absolute_safe_path(values,"STACKS_ROOT"),restore_live._absolute_safe_path(values,"BASE_PATH"))
def resume(backup_set:Path,bootstrap:Path)->dict[str,object]:
 c=_prepare_resume_context(backup_set,bootstrap);verify_source(c.backup_set,c.stacks_root,c.source_commit);verify_env(c.env_artifact,c.stacks_root);verify_prepared(c.stacks_root,c.resolved_stacks);pg=postgres_table_count(c.values);gt,gr=gitea_state(c.base_path);mh=verify_memory(c.base_path,c.values);verify_bootstrap(c.bootstrap,c.base_path,c.values);resolved=list(c.resolved_stacks);restore_compat.wait_required_runtime(c.stacks_root,resolved,timeout=240);restore_compat.install_with_readiness_compat(c.stacks_root,resolved,reconcile=True,label="final restore READY/VERIFY/reconcile");enable_memory_sync(c.stacks_root,c.base_path,c.values);restore_compat.install_with_readiness_compat(c.stacks_root,resolved,reconcile=False,label="post-resume final verification");return {"backup_set":str(c.backup_set),"source_commit":c.source_commit,"resolved_stacks":resolved,"postgres_tables":pg,"gitea_tables":gt,"gitea_repositories":gr,"memory_head":mh,"memory_sync_enabled":True,"status":"PASS"}
