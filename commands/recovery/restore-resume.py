#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Legacy-compatible CLI wrapper for the importable restore-resume engine."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
import dr,dr_restore_all,dr_restore_compat,dr_restore_live
from dr_restore_resume import ResumeError,resume

def main()->int:
 parser=argparse.ArgumentParser(description="Resume a clean-target restore stopped at the historical post-reconcile readiness race")
 parser.add_argument("backup_set");parser.add_argument("--memory-sync-ssh-bootstrap",required=True);parser.add_argument("--json",action="store_true");args=parser.parse_args()
 try:result=resume(Path(args.backup_set),Path(args.memory_sync_ssh_bootstrap))
 except (ResumeError,dr_restore_compat.RestoreCompatibilityError,dr_restore_all.RestoreAllError,dr_restore_live.RestoreLiveError,dr.RecoveryError,OSError,ValueError) as exc:
  print(f"RESTORE RESUME ERROR: {exc}",file=sys.stderr);return 1
 if args.json:print(json.dumps(result,indent=2,sort_keys=True))
 else:
  print("RESTORE ALL RESUME: PASS");print(f"- source commit: {result['source_commit']}");print(f"- resolved stacks: {','.join(str(v) for v in result['resolved_stacks'])}");print(f"- LiteLLM PostgreSQL tables: {result['postgres_tables']}");print(f"- Gitea SQLite tables: {result['gitea_tables']}");print(f"- Gitea repositories: {result['gitea_repositories']}");print(f"- portable memory HEAD: {result['memory_head']}");print("- Stack6 memory-sync profile: running");print("- Stack6 Git-memory desired state: enabled")
 return 0
if __name__=="__main__":raise SystemExit(main())
