# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Contracts for Bash/Zsh completion generation and installation."""
from __future__ import annotations
import contextlib,io,tempfile,unittest
from pathlib import Path
from unittest import mock
from commands import cli,completion
class CompletionTests(unittest.TestCase):
 def test_top_level_completion(self):
  values=completion.complete([""]);self.assertIn("upgrade",values);self.assertIn("completion",values);self.assertIn("--json",values);self.assertIn("--yes",values);self.assertEqual(completion.complete(["up"]),["upgrade"])
  values=completion.complete(["completion",""]);self.assertEqual([v for v in values if not v.startswith("--")],["bash","install","status","zsh"]);self.assertIn("--json",values);self.assertIn("--yes",values)
 def test_stack_completion_is_manifest_driven_and_numeric(self):
  with mock.patch("commands.completion.install.all_manifests",return_value={0:{},2:{},7:{}}):
   self.assertEqual([v for v in completion.complete(["start",""]) if not v.startswith("--")],["0","2","7"]);self.assertEqual([v for v in completion.complete(["stop",""]) if not v.startswith("--")],["0","2","7"]);self.assertEqual(completion.complete(["start","stack"]),[])
 def test_upgrade_components_are_manifest_driven_with_numeric_public_stack(self):
  compiled={"schema_version":1,"stacks":[{"id":"stack2","components":[{"id":"redis"},{"id":"searxng"}]}]}
  with mock.patch("commands.completion.component_inventory.compile_upgrade_catalog",return_value=compiled),mock.patch("commands.completion.install.all_manifests",return_value={2:{}}):
   self.assertEqual([v for v in completion.complete(["upgrade","2",""]) if not v.startswith("--")],["redis","searxng"]);self.assertEqual([v for v in completion.complete(["upgrade","stack2",""]) if not v.startswith("--")],[])
 def test_upgrade_actions_match_public_grammar(self):
  compiled={"schema_version":1,"stacks":[{"id":"stack7","components":[{"id":"open-webui"}]}]}
  with mock.patch("commands.completion.component_inventory.compile_upgrade_catalog",return_value=compiled),mock.patch("commands.completion.install.all_manifests",return_value={7:{}}):
   self.assertEqual([v for v in completion.complete(["upgrade","7","open-webui",""]) if not v.startswith("--")],["clear","select"]);self.assertEqual([v for v in completion.complete(["upgrade","policy","7","open-webui",""]) if not v.startswith("--")],["clear","set"])
 def test_global_flags_are_available_at_nested_leaves(self):
  for words in (["restore","plan","/backup",""] ,["inventory","rescan",""] ,["upgrade","check",""]):
   with self.subTest(words=words):
    values=completion.complete(list(words));self.assertIn("--json",values);self.assertIn("--yes",values)
 def test_shell_scripts_delegate_to_private_endpoint(self):self.assertIn("__complete",completion.shell_script("bash"));self.assertIn("__complete",completion.shell_script("zsh"))
 def test_detect_shell_is_fail_closed(self):
  self.assertEqual(completion.detect_shell({"SHELL":"/bin/bash"}),"bash");self.assertEqual(completion.detect_shell({"SHELL":"/usr/bin/zsh"}),"zsh")
  with self.assertRaises(ValueError):completion.detect_shell({"SHELL":"/bin/fish"})
 def test_targets_distinguish_root_and_user(self):
  home=Path("/tmp/example-home");self.assertEqual(completion.completion_target("bash",euid=0,home=home),Path("/etc/bash_completion.d/local-ai"));self.assertEqual(completion.completion_target("bash",euid=1000,home=home),home/".local/share/bash-completion/completions/local-ai");self.assertEqual(completion.completion_target("zsh",euid=0,home=home),Path("/usr/local/share/zsh/site-functions/_local-ai"));self.assertEqual(completion.completion_target("zsh",euid=1000,home=home),home/".local/share/zsh/site-functions/_local-ai")
 def test_user_install_is_idempotent_and_status_matches_content(self):
  with tempfile.TemporaryDirectory() as tmp:
   home=Path(tmp);shell,target=completion.install_completion(environ={"SHELL":"/bin/bash"},euid=1000,home=home);first=target.read_text(encoding="utf-8");shell2,target2=completion.install_completion(environ={"SHELL":"/bin/bash"},euid=1000,home=home);self.assertEqual((shell,target),(shell2,target2));self.assertEqual(target.read_text(encoding="utf-8"),first);self.assertEqual(completion.completion_status(environ={"SHELL":"/bin/bash"},euid=1000,home=home),("bash",target,True))
 def test_private_endpoint_fails_quiet(self):
  with mock.patch("commands.completion.complete",side_effect=RuntimeError("boom")):self.assertEqual(cli.main(["__complete","upgrade",""]),0)
 def test_completion_command_emits_shell_adapter(self):
  output=io.StringIO()
  with contextlib.redirect_stdout(output):rc=cli.main(["completion","bash"])
  self.assertEqual(rc,0);self.assertIn("__complete",output.getvalue())
if __name__=="__main__":unittest.main()
