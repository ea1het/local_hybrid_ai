#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Read-only platform diagnostics exposed through ``./local-ai doctor``."""
from __future__ import annotations
import os,shutil,stat,subprocess
from pathlib import Path
from local_ai_cli.common import runtime as install
from local_ai_cli.common import component_inventory
SCHEMA_VERSION="1";ROOT=Path(__file__).resolve().parents[3]
def _check(check_id,status,message,**details):return {"id":check_id,"status":status,"message":message,"details":details}
def run_checks():
 checks=[];entry=ROOT/"local-ai";checks.append(_check("management_entrypoint","pass" if entry.is_file() else "fail","root management entry point is present" if entry.is_file() else "root management entry point is missing"))
 try:manifests=install.all_manifests();lifecycle=install.load_lifecycle();install.validate_registry(manifests,lifecycle)
 except (install.ManifestError,OSError,subprocess.CalledProcessError) as exc:checks.append(_check("lifecycle_registry","fail","manifest/lifecycle registry validation failed",error=str(exc)))
 else:checks.append(_check("lifecycle_registry","pass","manifest and lifecycle registries agree",stacks=len(manifests)))
 try:components=component_inventory.compile_components()
 except (component_inventory.ComponentInventoryError,OSError,subprocess.CalledProcessError) as exc:checks.append(_check("component_inventory","fail","manifest component inventory validation failed",error=str(exc)))
 else:checks.append(_check("component_inventory","pass","manifest component ownership and Compose bindings agree",components=len(components)))
 env_path=ROOT/".env"
 if not env_path.is_file():checks.append(_check("operational_env","fail","protected operational .env is missing"))
 else:
  mode=stat.S_IMODE(env_path.stat().st_mode);checks.append(_check("operational_env","pass" if mode==0o600 else "fail","protected operational .env is present with mode 0600" if mode==0o600 else "protected operational .env must use mode 0600",**({} if mode==0o600 else {"mode":f"{mode:04o}"})))
 docker=shutil.which("docker")
 if docker is None:checks.extend([_check("docker_cli","fail","docker CLI is not available"),_check("docker_compose","fail","docker compose cannot be checked without docker CLI")])
 else:
  checks.append(_check("docker_cli","pass","docker CLI is available",path=docker));cp=subprocess.run([docker,"compose","version"],cwd=ROOT,text=True,capture_output=True,check=False);checks.append(_check("docker_compose","pass" if cp.returncode==0 else "fail","docker compose is available" if cp.returncode==0 else "docker compose command failed",**({} if cp.returncode==0 else {"returncode":cp.returncode})))
 runtime_root=Path(os.environ.get("LOCAL_AI_RUNTIME_ROOT","/opt/docker/runtime"));checks.append(_check("runtime_root","pass" if runtime_root.exists() and runtime_root.is_dir() else "warn","runtime root exists" if runtime_root.exists() and runtime_root.is_dir() else "runtime root does not exist yet",configured=runtime_root.exists() and runtime_root.is_dir()));return checks
def json_payload(checks=None):
 records=run_checks() if checks is None else checks;success=not any(item["status"]=="fail" for item in records);return {"schema_version":SCHEMA_VERSION,"command":"doctor","success":success,"checks":records}
payload=json_payload
def cli_text(result):
 lines=[f"{item['status'].upper():4}  {item['id']}: {item['message']}" for item in result["checks"]];lines.append("DOCTOR: PASS" if result["success"] else "DOCTOR: FAIL");return "\n".join(lines)
def main(*,json_output=False):
 from local_ai_cli.common import render
 result=json_payload();render.render_json(result) if json_output else render.render_cli(cli_text(result));return 0 if result["success"] else 1
