#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Regression tests for policy owned by local_ai_cli.cli rather than the launcher."""
from __future__ import annotations
import io,json,unittest
from contextlib import redirect_stdout,redirect_stderr
from pathlib import Path
from unittest import mock
from local_ai_cli import cli
ROOT=Path(__file__).resolve().parents[1]
class CliCentralizationTests(unittest.TestCase):
 def test_launcher_and_public_dispatcher_contain_no_human_input(self):
  launcher=(ROOT/"local-ai").read_text(encoding="utf-8");dispatcher=(ROOT/"src"/"local_ai_cli"/"cli.py").read_text(encoding="utf-8")
  self.assertNotIn("argparse",launcher);self.assertNotIn("_facade_help",launcher);self.assertIn("local_ai_cli.cli import main",launcher);self.assertNotIn("input(",launcher);self.assertNotIn("input(",dispatcher);self.assertNotIn("_interactive_consent",dispatcher)
 def test_public_dispatcher_does_not_depend_on_recovery_compatibility_package(self):
  dispatcher=(ROOT/"src"/"local_ai_cli"/"cli.py").read_text(encoding="utf-8")
  self.assertNotIn("local_ai_cli.recovery",dispatcher);self.assertNotIn('commands/recovery',dispatcher);self.assertNotIn("recovery_api",dispatcher)
 def test_inventory_rescan_json_fails_closed_without_yes_before_domain_write(self):
  out,err=io.StringIO(),io.StringIO()
  with mock.patch("local_ai_cli.cli.inventory.json_payload") as payload,redirect_stdout(out),redirect_stderr(err):rc=cli.main(["--json","inventory","rescan"])
  self.assertEqual(rc,2);payload.assert_not_called();self.assertEqual(err.getvalue(),"");result=json.loads(out.getvalue());self.assertEqual(result["command"],"inventory.rescan");self.assertEqual(result["error"]["code"],"CONFIRMATION_REQUIRED")
 def test_inventory_rescan_fails_closed_without_yes(self):
  with mock.patch("local_ai_cli.cli.inventory.json_payload") as payload:rc=cli.main(["inventory","rescan"])
  self.assertEqual(rc,2);payload.assert_not_called()
 def test_inventory_rescan_yes_reaches_domain_once(self):
  result={"schema_version":"1","command":"inventory.rescan","success":True,"component_count":0,"snapshot":"/tmp/component-inventory.json","source_fingerprint":"sha256:x","diff":{"added":[],"removed":[],"changed":[]}}
  with mock.patch("local_ai_cli.cli.inventory.json_payload",return_value=result) as payload,mock.patch("local_ai_cli.cli.inventory.cli_text",return_value="ok"),mock.patch("local_ai_cli.cli.render.render_cli"):rc=cli.main(["inventory","rescan","--yes"])
  self.assertEqual(rc,0);payload.assert_called_once_with(["rescan"])
 def test_start_stop_reject_every_out_of_range_public_selector_before_runtime(self):
  for command in ("start","stop"):
   for selector in ("stack7","8","99","-1"):
    with self.subTest(command=command,selector=selector),mock.patch("local_ai_cli.cli.lifecycle.json_payload") as runtime:rc=cli.main([command,selector])
    self.assertEqual(rc,2);runtime.assert_not_called()
 def test_upgrade_rejects_out_of_range_selector_before_upgrade_domain(self):
  for selector in ("stack7","8","99","-1"):
   with self.subTest(selector=selector),mock.patch("local_ai_cli.cli.upgrade_entry.build_payload") as build:rc=cli.main(["upgrade",selector,"open-webui","clear"])
   self.assertEqual(rc,2);build.assert_not_called()
if __name__=="__main__":unittest.main()
