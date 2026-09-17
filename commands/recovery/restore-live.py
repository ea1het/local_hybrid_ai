#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Legacy-compatible CLI wrapper for the importable clean-target restore service."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
import dr,dr_restore_all,dr_restore_compat,dr_restore_live
from dr_restore_live_service import BootstrapError,check_clean,execute

def main()->int:
 parser=argparse.ArgumentParser(description="Clean-target full restore for local_hybrid_ai");parser.add_argument("backup_set");mode=parser.add_mutually_exclusive_group(required=True);mode.add_argument("--check-clean-target",action="store_true");mode.add_argument("--execute",action="store_true");parser.add_argument("--confirm-clean-target",action="store_true",help="mandatory with --execute");parser.add_argument("--memory-sync-ssh-bootstrap",default=None,help="external operator-owned SSH material directory used only to reprovision Stack6 memory-sync after a clean rebuild");parser.add_argument("--json",action="store_true");args=parser.parse_args();backup_set=Path(args.backup_set)
 try:
  if args.check_clean_target:result=check_clean(backup_set)
  else:
   if not args.confirm_clean_target:raise dr_restore_live.RestoreLiveError("real restore requires explicit clean-target confirmation")
   result=execute(backup_set,Path(args.memory_sync_ssh_bootstrap) if args.memory_sync_ssh_bootstrap else None)
 except (BootstrapError,dr_restore_compat.RestoreCompatibilityError,dr_restore_live.RestoreLiveError,dr_restore_all.RestoreAllError,dr.RecoveryError,OSError,ValueError) as exc:print(f"RESTORE ALL ERROR: {exc}",file=sys.stderr);return 1
 if args.json:print(json.dumps(result,indent=2,sort_keys=True))
 elif args.check_clean_target:
  print("RESTORE ALL CLEAN-TARGET PREFLIGHT: PASS");print(f"- backup set: {result['backup_set']}");print(f"- source commit: {result['source_commit']}");print(f"- resolved stacks: {','.join(str(v) for v in result['resolved_stacks'])}");print(f"- checksums verified: {result['checksums_verified']}");print(f"- STACKS_ROOT: {result['stacks_root']}");print(f"- BASE_PATH: {result['base_path']}");print("- changes made: no")
 else:
  print("RESTORE ALL CLEAN TARGET: PASS");print(f"- backup set: {result['backup_set']}");print(f"- source commit: {result['source_commit']}");print(f"- resolved stacks: {','.join(str(v) for v in result['resolved_stacks'])}");print(f"- LiteLLM PostgreSQL tables restored: {result['postgres_tables']}");print(f"- Gitea SQLite tables restored: {result['gitea_tables']}");print(f"- Gitea repositories restored: {result['gitea_repositories']}");print(f"- external Git resources restored: {result['external_git_restored']}");print(f"- STACKS_ROOT: {result['stacks_root']}");print(f"- BASE_PATH: {result['base_path']}")
  if args.memory_sync_ssh_bootstrap:print("- Stack6 memory-sync SSH bootstrap: reprovisioned from external operator material");print("- Stack6 memory-sync profile: running")
 return 0
if __name__=="__main__":raise SystemExit(main())
