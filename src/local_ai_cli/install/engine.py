#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Install-owned adapter around the package-private installer implementation."""
from __future__ import annotations
import subprocess
from pathlib import Path
from . import _engine_impl as impl
ROOT=Path(__file__).resolve().parents[3]
impl.ROOT=ROOT
impl.MANIFEST_TOOL=ROOT/"stack0_-_platform"/"manifests.py"
impl.LIFECYCLE_FILE=ROOT/"src"/"local_ai_cli"/"install-lifecycle.json"
def run(cmd,*,cwd=None,capture=False,check=True):
 return subprocess.run(cmd,cwd=ROOT if cwd is None else cwd,text=True,stdout=subprocess.PIPE if capture else None,stderr=subprocess.PIPE if capture else None,check=check)
impl.run=run
InstallerError=impl.InstallerError
Action=impl.Action
preflight=impl.preflight
all_manifests=impl.all_manifests
load_lifecycle=impl.load_lifecycle
validate_registry=impl.validate_registry
resolve_requested=impl.resolve_requested
resolve_plan=impl.resolve_plan
build_actions=impl.build_actions
wait_required_runtime=impl.wait_required_runtime
INTERNAL_WAIT_COMMAND=impl.INTERNAL_WAIT_COMMAND
def execute(actions,lifecycle):
 """Execute an already-resolved action list directly inside the Install domain."""
 for action in actions:
  if action.command==(INTERNAL_WAIT_COMMAND,):
   wait_required_runtime(action.stack_id,lifecycle["stacks"][str(action.stack_id)])
   continue
  run(list(action.command),cwd=ROOT/action.directory,check=True)
