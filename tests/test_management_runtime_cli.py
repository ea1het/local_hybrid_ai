# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Public CLI dispatch tests for selective stack runtime start/stop."""
from __future__ import annotations
import contextlib,io,unittest
from unittest import mock
from commands import cli
class ManagementRuntimeCliTests(unittest.TestCase):
 def test_start_dispatches_numeric_stack_selector_through_public_cli(self):
  payload={"success":True,"command":"runtime.start","stack":"stack7","directory":"stack7_-_open-webui","containers":["open-webui"]}
  with mock.patch("commands.cli.runtime_lifecycle.json_payload",return_value=payload) as runtime,mock.patch("commands.cli.runtime_lifecycle.cli_text",return_value="ok"),mock.patch("commands.cli.render.render_cli"):
   rc=cli.main(["start","7","--yes"])
  self.assertEqual(rc,0);runtime.assert_called_once_with("start","7")
 def test_internal_stack_name_is_rejected_at_public_boundary(self):
  stderr=io.StringIO()
  with contextlib.redirect_stderr(stderr),mock.patch("commands.cli.runtime_lifecycle.json_payload") as runtime:rc=cli.main(["stop","stack7","--yes"])
  self.assertEqual(rc,2);self.assertIn("STACK_SELECTOR_INVALID",stderr.getvalue());runtime.assert_not_called()
 def test_manifest_directory_is_rejected_at_public_boundary(self):
  stderr=io.StringIO()
  with contextlib.redirect_stderr(stderr),mock.patch("commands.cli.runtime_lifecycle.json_payload") as runtime:rc=cli.main(["stop","stack7_-_open-webui","--yes"])
  self.assertEqual(rc,2);self.assertIn("STACK_SELECTOR_INVALID",stderr.getvalue());runtime.assert_not_called()
 def test_json_flag_is_owned_by_public_renderer(self):
  payload={"success":True,"command":"runtime.start","stack":"stack7","directory":"stack7_-_open-webui","containers":["open-webui"]}
  with mock.patch("commands.cli.runtime_lifecycle.json_payload",return_value=payload) as runtime,mock.patch("commands.cli.render.render_json") as renderer:
   rc=cli.main(["--json","start","7","--yes"])
  self.assertEqual(rc,0);runtime.assert_called_once_with("start","7");renderer.assert_called_once_with(payload)
 def test_runtime_mutation_noninteractive_requires_yes(self):
  with mock.patch.object(cli.sys.stdin,"isatty",return_value=False),mock.patch("commands.cli.runtime_lifecycle.json_payload") as runtime:
   rc=cli.main(["start","7"])
  self.assertEqual(rc,2);runtime.assert_not_called()
 def test_runtime_mutation_json_requires_yes(self):
  out=io.StringIO()
  with contextlib.redirect_stdout(out),mock.patch("commands.cli.runtime_lifecycle.json_payload") as runtime:
   rc=cli.main(["stop","7","--json"])
  self.assertEqual(rc,2);runtime.assert_not_called();self.assertIn("CONFIRMATION_REQUIRED",out.getvalue())
if __name__=="__main__":unittest.main()
