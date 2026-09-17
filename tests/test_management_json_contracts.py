# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Stable JSON contracts for the public management boundary."""
from __future__ import annotations
import io,json,unittest
from contextlib import redirect_stdout,redirect_stderr
from unittest import mock
from commands import cli,install_entry
class ManagementJsonContractTests(unittest.TestCase):
 def _install_boundary(self,argv):
  manifests={7:{"directory":"stack7_-_open-webui"}};lifecycle={"stacks":{"7":{}}}
  with mock.patch("commands.install_entry.install.preflight"),mock.patch("commands.install_entry.install.all_manifests",return_value=manifests),mock.patch("commands.install_entry.install.load_lifecycle",return_value=lifecycle),mock.patch("commands.install_entry.install.validate_registry"),mock.patch("commands.install_entry.install.resolve_requested",return_value=[7]),mock.patch("commands.install_entry.install.resolve_plan",return_value=[7]),mock.patch("commands.install_entry.install.build_actions",return_value=([],[],set())):return install_entry.build_payload(argv)
 def test_install_plan_json_exposes_high_level_lifecycle_without_private_commands(self):
  manifests={7:{"directory":"stack7_-_open-webui"}};lifecycle={"stacks":{"7":{}}};action=mock.Mock(stack_id=7,phase="verify",reason="validate stack-owned contract")
  with mock.patch("commands.install_entry.install.preflight"),mock.patch("commands.install_entry.install.all_manifests",return_value=manifests),mock.patch("commands.install_entry.install.load_lifecycle",return_value=lifecycle),mock.patch("commands.install_entry.install.validate_registry"),mock.patch("commands.install_entry.install.resolve_requested",return_value=[7]),mock.patch("commands.install_entry.install.resolve_plan",return_value=[7]),mock.patch("commands.install_entry.install.build_actions",return_value=([action],[],set())):payload,rc=install_entry.build_payload(["7","--plan"])
  self.assertEqual(rc,0);self.assertEqual(payload["schema_version"],"1");self.assertEqual(payload["command"],"install");self.assertEqual(payload["resolved_stacks"],["stack7"]);self.assertNotIn("command_line",payload["actions"][0])
 def test_install_execute_uses_transversal_confirmation_contract(self):
  payload,rc=self._install_boundary(["7"]);self.assertEqual(rc,2);self.assertEqual(payload["error"]["code"],"CONFIRMATION_REQUIRED")
 def test_install_rejects_private_and_out_of_range_stack_selectors_before_preflight(self):
  for selector in ("stack7","8","-1"):
   with self.subTest(selector=selector),mock.patch("commands.install_entry.install.preflight") as preflight:
    payload,rc=install_entry.build_payload([selector,"--plan"])
   self.assertEqual(rc,2);self.assertEqual(payload["error"]["code"],"CLI_USAGE");preflight.assert_not_called()
 def test_install_parser_error_is_structured_without_argparse_stderr(self):
  err=io.StringIO()
  with redirect_stderr(err):payload,rc=install_entry.build_payload(["7","--plan","--dry-run"])
  self.assertEqual(rc,2);self.assertEqual(err.getvalue(),"");self.assertEqual(payload["error"]["code"],"CLI_USAGE")
 def test_restore_json_renders_structured_service_result_unchanged(self):
  service_payload={"schema_version":"1","command":"restore.plan","success":True,"result":{"resolved_stacks":[0,1]}};out=io.StringIO()
  with mock.patch("commands.cli.recovery_api.plan_payload",return_value=service_payload),redirect_stdout(out):rc=cli.restore_command(["plan","/backup"],cli.CLIContext(json_output=True))
  self.assertEqual(rc,0);self.assertEqual(json.loads(out.getvalue()),service_payload)
 def test_restore_json_failure_is_single_structured_document(self):
  service_payload={"schema_version":"1","command":"restore.plan","success":False,"error":{"code":"RESTORE_PLAN_FAILED","message":"restore failed"}};out=io.StringIO()
  with mock.patch("commands.cli.recovery_api.plan_payload",return_value=service_payload),redirect_stdout(out):rc=cli.restore_command(["plan","/backup"],cli.CLIContext(json_output=True))
  self.assertEqual(rc,1);self.assertEqual(json.loads(out.getvalue()),service_payload)
 def test_json_parser_errors_are_one_machine_document_and_silent_on_stderr(self):
  cases=(["--json","backup","--bogus"],["restore","apply","/backup","--json"],["--json","restore","drill","/backup"],["--json","start"])
  for argv in cases:
   out,err=io.StringIO(),io.StringIO()
   with self.subTest(argv=argv),redirect_stdout(out),redirect_stderr(err):rc=cli.main(list(argv))
   self.assertEqual(rc,2);self.assertEqual(err.getvalue(),"");payload=json.loads(out.getvalue());self.assertFalse(payload["success"]);self.assertEqual(payload["error"]["code"],"CLI_USAGE")
 def test_restore_semantic_usage_error_is_json_safe(self):
  out,err=io.StringIO(),io.StringIO()
  with redirect_stdout(out),redirect_stderr(err):rc=cli.main(["restore","apply","/backup","--check-clean-target","--confirm-clean-target","--json"])
  self.assertEqual(rc,2);self.assertEqual(err.getvalue(),"");self.assertEqual(json.loads(out.getvalue())["error"]["code"],"CLI_USAGE")
if __name__=="__main__":unittest.main()
