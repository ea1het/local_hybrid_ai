# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Regression tests for policy owned by commands.cli rather than the launcher."""
from __future__ import annotations
import io,json,sys,unittest
from contextlib import redirect_stdout,redirect_stderr
from pathlib import Path
from unittest import mock
from commands import cli
ROOT=Path(__file__).resolve().parents[1]
class CliCentralizationTests(unittest.TestCase):
 def test_launcher_is_thin_and_contains_no_public_grammar(self):
  text=(ROOT/"local-ai").read_text(encoding="utf-8")
  self.assertNotIn("argparse",text);self.assertNotIn("_facade_help",text);self.assertNotIn("input(",text);self.assertIn("commands.cli import main",text)
 def test_inventory_rescan_json_fails_closed_without_yes_before_domain_write(self):
  out,err=io.StringIO(),io.StringIO()
  with mock.patch("commands.cli.inventory.json_payload") as payload,redirect_stdout(out),redirect_stderr(err):rc=cli.main(["--json","inventory","rescan"])
  self.assertEqual(rc,2);payload.assert_not_called();self.assertEqual(err.getvalue(),"");result=json.loads(out.getvalue());self.assertEqual(result["command"],"inventory.rescan");self.assertEqual(result["error"]["code"],"CONFIRMATION_REQUIRED")
 def test_inventory_rescan_noninteractive_fails_closed_without_yes(self):
  with mock.patch.object(sys.stdin,"isatty",return_value=False),mock.patch("commands.cli.inventory.json_payload") as payload:rc=cli.main(["inventory","rescan"])
  self.assertEqual(rc,2);payload.assert_not_called()
 def test_inventory_rescan_yes_reaches_domain_once(self):
  result={"schema_version":"1","command":"inventory.rescan","success":True,"component_count":0,"snapshot":"/tmp/component-inventory.json","source_fingerprint":"sha256:x","diff":{"added":[],"removed":[],"changed":[]}}
  with mock.patch("commands.cli.inventory.json_payload",return_value=result) as payload,mock.patch("commands.cli.inventory.cli_text",return_value="ok"),mock.patch("commands.cli.render.render_cli"):rc=cli.main(["inventory","rescan","--yes"])
  self.assertEqual(rc,0);payload.assert_called_once_with(["rescan"])
 def test_inventory_rescan_interactive_yes_is_converted_to_public_consent(self):
  result={"schema_version":"1","command":"inventory.rescan","success":True,"component_count":0,"snapshot":"/tmp/component-inventory.json","source_fingerprint":"sha256:x","diff":{"added":[],"removed":[],"changed":[]}}
  with mock.patch.object(sys.stdin,"isatty",return_value=True),mock.patch("builtins.input",return_value="yes"),mock.patch("commands.cli.inventory.json_payload",return_value=result) as payload,mock.patch("commands.cli.inventory.cli_text",return_value="ok"),mock.patch("commands.cli.render.render_cli"):rc=cli.main(["inventory","rescan"])
  self.assertEqual(rc,0);payload.assert_called_once_with(["rescan"])
 def test_start_stop_reject_every_out_of_range_public_selector_before_runtime(self):
  for command in ("start","stop"):
   for selector in ("stack7","8","99","-1"):
    with self.subTest(command=command,selector=selector),mock.patch("commands.cli.runtime_lifecycle.json_payload") as runtime:rc=cli.main([command,selector])
    self.assertEqual(rc,2);runtime.assert_not_called()
 def test_upgrade_rejects_out_of_range_selector_before_upgrade_domain(self):
  for selector in ("stack7","8","99","-1"):
   with self.subTest(selector=selector),mock.patch("commands.cli.upgrade_entry.build_payload") as build:rc=cli.main(["upgrade",selector,"open-webui","clear"])
   self.assertEqual(rc,2);build.assert_not_called()
if __name__=="__main__":unittest.main()
