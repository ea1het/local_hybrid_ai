# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Focused safety regressions for the public backup/restore boundary."""
from __future__ import annotations
import contextlib,io,json,tempfile,unittest
from pathlib import Path
from unittest import mock
from commands import cli
class RecoveryPublicCliSafetyTests(unittest.TestCase):
 def _write_set(self,root,metadata):
  backup=root/"backup-20260916T120000Z";backup.mkdir();(backup/"backup.json").write_text(json.dumps(metadata),encoding="utf-8");(backup/"checksums.sha256").write_text("x\n",encoding="utf-8")
 def _valid_metadata(self):return {"schema_version":1,"kind":"local-hybrid-ai-backup-set","created_at":"2026-09-16T12:00:00+00:00","source_commit":"a"*40,"requested_selector":"all","requested_stacks":[0,3,6],"resolved_stacks":[0,3,6],"artifacts":[],"prerequisites":[]}
 def test_backup_listing_rejects_boolean_schema_version(self):
  metadata=self._valid_metadata();metadata["schema_version"]=True
  with tempfile.TemporaryDirectory() as tmp:self._write_set(Path(tmp),metadata);records=cli._backup_sets(Path(tmp))
  self.assertEqual(records[0]["status"],"invalid")
 def test_backup_listing_rejects_malformed_source_commit(self):
  metadata=self._valid_metadata();metadata["source_commit"]="not-a-commit"
  with tempfile.TemporaryDirectory() as tmp:self._write_set(Path(tmp),metadata);records=cli._backup_sets(Path(tmp))
  self.assertEqual(records[0]["status"],"invalid")
 def test_backup_listing_rejects_unknown_metadata_field(self):
  metadata=self._valid_metadata();metadata["unexpected"]="field"
  with tempfile.TemporaryDirectory() as tmp:self._write_set(Path(tmp),metadata);records=cli._backup_sets(Path(tmp))
  self.assertEqual(records[0]["status"],"invalid")
 def test_restore_execute_requires_clean_target_confirmation(self):
  err=io.StringIO()
  with contextlib.redirect_stderr(err),mock.patch.object(cli.recovery_api,"apply_payload") as run:rc=cli.restore_command(["apply","/backup/set","--execute"],cli.CLIContext(assume_yes=True))
  self.assertEqual(rc,2);self.assertIn("CLI_USAGE",err.getvalue());run.assert_not_called()
 def test_restore_preflight_rejects_execution_confirmation(self):
  err=io.StringIO()
  with contextlib.redirect_stderr(err),mock.patch.object(cli.recovery_api,"check_clean_target_payload") as run:rc=cli.restore_command(["apply","/backup/set","--check-clean-target","--confirm-clean-target"],cli.CLIContext())
  self.assertEqual(rc,2);self.assertIn("CLI_USAGE",err.getvalue());run.assert_not_called()
 def test_restore_execute_requires_global_yes_noninteractive(self):
  with mock.patch.object(cli.sys.stdin,"isatty",return_value=False),mock.patch.object(cli.recovery_api,"apply_payload") as run:rc=cli.restore_command(["apply","/backup/set","--execute","--confirm-clean-target"],cli.CLIContext())
  self.assertEqual(rc,2);run.assert_not_called()
 def test_restore_execute_with_both_confirmations_reaches_structured_engine(self):
  payload={"schema_version":"1","command":"restore.apply","success":True,"result":{"changes_made":True}}
  with mock.patch.object(cli.recovery_api,"apply_payload",return_value=payload) as run,mock.patch.object(cli,"_run_internal") as internal,mock.patch.object(cli.render,"render_cli"):
   rc=cli.restore_command(["apply","/backup/set","--execute","--confirm-clean-target"],cli.CLIContext(assume_yes=True))
  self.assertEqual(rc,0);run.assert_called_once_with("/backup/set",None);internal.assert_not_called()
 def test_restore_check_clean_target_is_read_only_and_needs_no_yes(self):
  payload={"schema_version":"1","command":"restore.apply","success":True,"result":{"clean_target":True,"changes_made":False}}
  with mock.patch.object(cli.recovery_api,"check_clean_target_payload",return_value=payload) as run,mock.patch.object(cli.render,"render_json"):
   rc=cli.restore_command(["apply","/backup/set","--check-clean-target"],cli.CLIContext(json_output=True))
  self.assertEqual(rc,0);run.assert_called_once_with("/backup/set")
 def test_restore_drill_requires_yes_noninteractive(self):
  with mock.patch.object(cli.sys.stdin,"isatty",return_value=False),mock.patch.object(cli.recovery_api,"drill_payload") as run:
   rc=cli.restore_command(["drill","/backup/set","--destination","/tmp/drill"],cli.CLIContext())
  self.assertEqual(rc,2);run.assert_not_called()
 def test_restore_resume_requires_yes_noninteractive(self):
  with mock.patch.object(cli.sys.stdin,"isatty",return_value=False),mock.patch.object(cli.recovery_api,"resume_payload") as run:
   rc=cli.restore_command(["resume","/backup/set","--memory-sync-ssh-bootstrap","/ssh"],cli.CLIContext())
  self.assertEqual(rc,2);run.assert_not_called()
 def test_restore_resume_reaches_structured_engine_with_yes(self):
  payload={"schema_version":"1","command":"restore.resume","success":True,"result":{"memory_sync_enabled":True}}
  with mock.patch.object(cli.recovery_api,"resume_payload",return_value=payload) as run,mock.patch.object(cli,"_run_internal") as internal,mock.patch.object(cli.render,"render_json"):
   rc=cli.restore_command(["resume","/backup/set","--memory-sync-ssh-bootstrap","/ssh"],cli.CLIContext(json_output=True,assume_yes=True))
  self.assertEqual(rc,0);run.assert_called_once_with("/backup/set","/ssh");internal.assert_not_called()
if __name__=="__main__":unittest.main()
