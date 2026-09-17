# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Contracts for the structured recovery API used by the public CLI."""
from __future__ import annotations
import unittest
from unittest import mock
from commands import cli
from commands.recovery import public_api
class RecoveryStructuredApiTests(unittest.TestCase):
 def test_plan_returns_serializable_public_envelope_without_rendering(self):
  plan=mock.Mock();plan.as_dict.return_value={"kind":"local-hybrid-ai-restore-plan","changes_made":False};engine=mock.Mock();engine.plan_restore_all.return_value=plan
  with mock.patch.object(public_api,"_load",return_value=engine):payload=public_api.plan_payload("/backup/set")
  self.assertEqual(payload["command"],"restore.plan");self.assertTrue(payload["success"])
 def test_plan_failure_is_stable_public_envelope(self):
  engine=mock.Mock();engine.plan_restore_all.side_effect=ValueError("bad recovery point")
  with mock.patch.object(public_api,"_load",return_value=engine):payload=public_api.plan_payload("/backup/set")
  self.assertFalse(payload["success"]);self.assertEqual(payload["error"]["code"],"RESTORE_PLAN_FAILED")
 def test_drill_returns_serializable_public_envelope_without_rendering(self):
  result=mock.Mock();result.as_dict.return_value={"destination":"/tmp/drill"};engine=mock.Mock();engine.run_restore_drill.return_value=result
  with mock.patch.object(public_api,"_load",return_value=engine):payload=public_api.drill_payload("/backup/set","/tmp/drill")
  self.assertTrue(payload["success"])
 def test_clean_target_preflight_uses_importable_service(self):
  service=mock.Mock();service.check_clean.return_value={"clean_target":True,"changes_made":False}
  with mock.patch.object(public_api,"_load",return_value=service) as load:payload=public_api.check_clean_target_payload("/backup/set")
  load.assert_called_once_with("dr_restore_live_service");service.check_clean.assert_called_once();self.assertTrue(payload["success"])
 def test_live_apply_uses_importable_service(self):
  service=mock.Mock();service.execute.return_value={"source_commit":"abc","postgres_tables":4}
  with mock.patch.object(public_api,"_load",return_value=service) as load:payload=public_api.apply_payload("/backup/set","/operator/ssh")
  load.assert_called_once_with("dr_restore_live_service");service.execute.assert_called_once();self.assertTrue(payload["success"])
 def test_live_apply_failure_is_stable_public_envelope(self):
  service=mock.Mock();service.execute.side_effect=OSError("restore failed")
  with mock.patch.object(public_api,"_load",return_value=service):payload=public_api.apply_payload("/backup/set")
  self.assertFalse(payload["success"]);self.assertEqual(payload["error"]["code"],"RESTORE_APPLY_FAILED")
 def test_resume_uses_importable_engine(self):
  engine=mock.Mock();engine.resume.return_value={"status":"PASS","memory_sync_enabled":True}
  with mock.patch.object(public_api,"_load",return_value=engine) as load:payload=public_api.resume_payload("/backup/set","/operator/ssh")
  load.assert_called_once_with("dr_restore_resume");engine.resume.assert_called_once();self.assertTrue(payload["success"])
 def test_failed_payload_has_human_error_text(self):
  text=public_api.cli_text({"schema_version":"1","command":"restore.resume","success":False,"error":{"code":"RESTORE_RESUME_FAILED","message":"broken"}});self.assertEqual(text,"RESTORE ERROR [RESTORE_RESUME_FAILED]: broken")
 def test_plan_public_dispatch_does_not_spawn_private_script(self):
  payload={"schema_version":"1","command":"restore.plan","success":True,"result":{"changes_made":False}}
  with mock.patch.object(cli.recovery_api,"plan_payload",return_value=payload),mock.patch.object(cli,"_run_internal") as internal,mock.patch.object(cli.render,"render_json"):rc=cli.restore_command(["plan","/backup/set"],cli.CLIContext(json_output=True))
  self.assertEqual(rc,0);internal.assert_not_called()
 def test_drill_public_dispatch_does_not_spawn_private_script(self):
  payload={"schema_version":"1","command":"restore.drill","success":True,"result":{"destination":"/tmp/drill"}}
  with mock.patch.object(cli.recovery_api,"drill_payload",return_value=payload),mock.patch.object(cli,"_run_internal") as internal,mock.patch.object(cli.render,"render_cli"):rc=cli.restore_command(["drill","/backup/set","--destination","/tmp/drill"],cli.CLIContext(assume_yes=True))
  self.assertEqual(rc,0);internal.assert_not_called()
 def test_public_dispatcher_has_no_private_json_rewrapper(self):
  source=(cli.ROOT/"commands"/"cli.py").read_text(encoding="utf-8");self.assertNotIn("def _run_internal_json",source)
 def test_public_api_does_not_load_legacy_entrypoint_scripts(self):
  source=(public_api.RECOVERY_ROOT/"public_api.py").read_text(encoding="utf-8");self.assertNotIn("spec_from_file_location",source);self.assertNotIn("restore-live.py",source);self.assertNotIn("restore-resume.py",source)
 def test_adapter_contains_no_rendering_or_subprocess_boundary(self):
  source=(public_api.RECOVERY_ROOT/"public_api.py").read_text(encoding="utf-8");self.assertNotIn("subprocess",source);self.assertNotIn("render_json",source);self.assertNotIn("json.dumps",source);self.assertNotIn("print(",source)
if __name__=="__main__":unittest.main()
