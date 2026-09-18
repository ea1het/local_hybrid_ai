#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Cross-command contract for public local-ai automation flags, help and rendering."""
from __future__ import annotations
import contextlib,io,json,re,subprocess,unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock
from local_ai_cli import cli,completion
from local_ai_cli.common import render
ROOT=Path(__file__).resolve().parents[1]
PUBLIC_HELP_PATHS=((),("install",),("backup",),("restore",),("restore","list-backup-sets"),("restore","plan"),("restore","drill"),("restore","apply"),("restore","resume"),("status",),("doctor",),("inventory",),("inventory","rescan"),("completion",),("completion","bash"),("completion","zsh"),("completion","install"),("completion","status"),("upgrade",),("upgrade","check"),("upgrade","adopt"),("upgrade","policy"),("upgrade","selectable"),("upgrade","7","open-webui","select"),("upgrade","7","open-webui","clear"),("start",),("stop",))
class GlobalCliContractTests(unittest.TestCase):
 def test_global_flags_are_position_independent(self):
  cases=[(["--json","--yes","status"],["status","--json","--yes"]),(["--yes","doctor","--json"],["doctor","--yes","--json"]),(["--json","--yes","inventory","rescan"],["inventory","rescan","--yes","--json"])]
  for left,right in cases:self.assertEqual(cli._extract_global_options(left),cli._extract_global_options(right))
 def test_every_completion_branch_exposes_global_flags(self):
  branches=[[""],["status",""],["doctor",""],["backup",""],["restore",""],["inventory",""],["start",""],["stop",""],["install",""],["upgrade",""] ,["completion",""]]
  for words in branches:
   values=completion.complete(words);self.assertIn("--json",values);self.assertIn("--yes",values)
 def test_every_public_help_path_documents_global_flags_and_hides_private_engines(self):
  private=("commands/","backup-all.py","restore-all.py","restore-drill.py","restore-live.py","restore-resume.py")
  for path in PUBLIC_HELP_PATHS:
   with self.subTest(path=path):
    cp=subprocess.run([str(ROOT/"local-ai"),*path,"--help"],cwd=ROOT,text=True,capture_output=True,check=False)
    self.assertEqual(cp.returncode,0,cp.stderr);self.assertIn("--json",cp.stdout);self.assertIn("--yes",cp.stdout)
    for token in private:self.assertNotIn(token,cp.stdout+cp.stderr)
 def test_upgrade_leaf_help_is_specific(self):
  check=subprocess.run([str(ROOT/"local-ai"),"upgrade","check","--help"],cwd=ROOT,text=True,capture_output=True,check=False);self.assertIn("--offline",check.stdout)
  policy=subprocess.run([str(ROOT/"local-ai"),"upgrade","policy","--help"],cwd=ROOT,text=True,capture_output=True,check=False);normalized=re.sub(r"\s*-\s*\n\s*", "-", policy.stdout);self.assertIn("manual",normalized);self.assertIn("minor-series",normalized);self.assertIn("major-series",normalized)
  selectable=subprocess.run([str(ROOT/"local-ai"),"upgrade","selectable","--help"],cwd=ROOT,text=True,capture_output=True,check=False);self.assertIn("enable",selectable.stdout);self.assertIn("disable",selectable.stdout);self.assertIn("clear",selectable.stdout)
  select=subprocess.run([str(ROOT/"local-ai"),"upgrade","7","open-webui","select","--help"],cwd=ROOT,text=True,capture_output=True,check=False);self.assertIn("VERSION",select.stdout);self.assertNotIn("--force",select.stdout)
 def test_restore_leaf_help_documents_global_flags(self):
  for action in ("list-backup-sets","plan","drill","apply","resume"):
   out=io.StringIO()
   with contextlib.redirect_stdout(out):
    with self.assertRaises(SystemExit) as raised:cli.build_restore_parser().parse_args([action,"--help"])
   self.assertEqual(raised.exception.code,0);self.assertIn("--json",out.getvalue());self.assertIn("--yes",out.getvalue())
 def test_render_json_emits_only_json(self):
  out=io.StringIO()
  with redirect_stdout(out):render.render_json({"success":True,"value":7})
  self.assertEqual(json.loads(out.getvalue()),{"success":True,"value":7})
 def test_render_cli_supports_custom_banner_and_header(self):
  out=io.StringIO()
  with redirect_stdout(out):render.render_cli("body",header="STATUS",banner="LOCAL-AI")
  self.assertEqual(out.getvalue(),"LOCAL-AI\n\nSTATUS\n\nbody\n")
 def test_read_only_commands_accept_yes_as_noop(self):
  with mock.patch("local_ai_cli.status.json_payload",return_value={"success":True,"stacks":[],"components":[]}),mock.patch("local_ai_cli.status.cli_text",return_value="ok"),mock.patch("local_ai_cli.common.render.render_cli"):self.assertEqual(cli.main(["status","--yes"]),0)
  with mock.patch("local_ai_cli.doctor.json_payload",return_value={"success":True,"checks":[]}),mock.patch("local_ai_cli.doctor.cli_text",return_value="ok"),mock.patch("local_ai_cli.common.render.render_cli"):self.assertEqual(cli.main(["doctor","--yes"]),0)
 def test_backup_yes_is_consumed_by_public_boundary(self):
  payload={"schema_version":"1","command":"backup","success":True,"result":{"path":"/backup/set","artifact_count":1}}
  with mock.patch.object(cli.backup,"backup_payload",return_value=payload) as run,mock.patch.object(cli.render,"render_cli"):self.assertEqual(cli.main(["--yes","backup"]),0)
  run.assert_called_once_with(None)
 def test_backup_json_yes_renders_one_public_document(self):
  payload={"schema_version":"1","command":"backup","success":True,"result":{"path":"/backup/set","artifact_count":1}};out=io.StringIO()
  with mock.patch.object(cli.backup,"backup_payload",return_value=payload),redirect_stdout(out):rc=cli.main(["backup","--json","--yes"])
  self.assertEqual(rc,0);self.assertEqual(json.loads(out.getvalue()),payload)
if __name__=="__main__":unittest.main()
