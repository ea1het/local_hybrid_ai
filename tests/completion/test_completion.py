# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Contracts owned by the Bash/Zsh completion command package."""
from __future__ import annotations
import contextlib,io,json,tempfile,unittest
from pathlib import Path
from unittest import mock
from commands import cli,completion
class CompletionTests(unittest.TestCase):
 def test_top_level_completion(self):
  values=completion.complete([""]);self.assertIn("upgrade",values);self.assertIn("completion",values);self.assertIn("--json",values);self.assertIn("--yes",values)
 def test_stack_completion_is_package_local(self):
  with mock.patch("commands.completion.api.manifests.all_manifests",return_value={0:{},2:{},7:{}}):self.assertEqual([v for v in completion.complete(["start",""]) if not v.startswith("--")],["0","2","7"])
 def test_install_completion_exposes_public_options(self):
  with mock.patch("commands.completion.api.manifests.all_manifests",return_value={0:{},7:{}}):values=completion.complete(["install",""])
  for value in ("0","7","--plan","--dry-run","--target","--reconcile","--json","--yes"):self.assertIn(value,values)
 def test_upgrade_components_are_package_local(self):
  with mock.patch("commands.completion.api.manifests.all_manifests",return_value={2:{}}),mock.patch("commands.completion.api.upgrade_components.upgrade_components",return_value=["redis","searxng"]):self.assertEqual([v for v in completion.complete(["upgrade","2",""]) if not v.startswith("--")],["redis","searxng"])
 def test_shell_scripts_delegate_to_private_endpoint(self):self.assertIn("__complete",completion.shell_script("bash"));self.assertIn("__complete",completion.shell_script("zsh"))
 def test_detect_shell_is_fail_closed(self):
  self.assertEqual(completion.detect_shell({"SHELL":"/bin/bash"}),"bash")
  with self.assertRaises(ValueError):completion.detect_shell({"SHELL":"/bin/fish"})
 def test_user_install_is_idempotent(self):
  with tempfile.TemporaryDirectory() as tmp:
   home=Path(tmp);shell,target=completion.install_completion(environ={"SHELL":"/bin/bash"},euid=1000,home=home);shell2,target2=completion.install_completion(environ={"SHELL":"/bin/bash"},euid=1000,home=home);self.assertEqual((shell,target),(shell2,target2))
 def test_public_json(self):
  out=io.StringIO()
  with contextlib.redirect_stdout(out):rc=cli.main(["completion","bash","--json"])
  self.assertEqual(rc,0);self.assertEqual(json.loads(out.getvalue())["command"],"completion.script")
if __name__=="__main__":unittest.main()
