# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Public management CLI contract tests."""
from __future__ import annotations
import json,os,subprocess,tempfile,unittest
from pathlib import Path
from unittest import mock
from local_ai_cli import cli,completion
ROOT=Path(__file__).resolve().parents[1]
class ManagementCliContractTests(unittest.TestCase):
 def run_cli(self,*args,runtime_root=None,env_extra=None):
  env=os.environ.copy()
  if runtime_root is not None:env["LOCAL_AI_RUNTIME_ROOT"]=runtime_root
  if env_extra:env.update(env_extra)
  return subprocess.run([str(ROOT/"local-ai"),*args],cwd=ROOT,env=env,text=True,stdin=subprocess.DEVNULL,capture_output=True,check=False)
 def test_root_help_exposes_supported_commands(self):
  cp=self.run_cli();self.assertEqual(cp.returncode,0,cp.stderr)
  for command in ("backup","completion","doctor","install","inventory","restore","start","status","stop","upgrade"):self.assertIn(command,cp.stdout)
 def test_start_and_stop_reject_internal_stack_names(self):
  for command in ("start","stop"):
   cp=self.run_cli(command,"stack7");self.assertEqual(cp.returncode,2);self.assertIn("STACK_SELECTOR_INVALID",cp.stderr)
 def test_completion_top_level_matches_public_commands_and_globals(self):
  values=completion.complete([""])
  for command in ("backup","completion","doctor","install","inventory","restore","start","status","stop","upgrade","--json","--yes"):self.assertIn(command,values)
 def test_completion_start_stop_stack_selectors_are_numeric(self):
  for command in ("start","stop"):
   values=completion.complete([command,""])
   for i in range(8):self.assertIn(str(i),values)
 def test_completion_backup_exposes_confirmation_destination_and_json(self):
  values=completion.complete(["backup",""])
  for item in ("--destination","--yes","--json"):self.assertIn(item,values)
 def test_completion_restore_actions_include_backup_listing(self):
  values=completion.complete(["restore",""])
  for item in ("apply","drill","list-backup-sets","plan","resume"):self.assertIn(item,values)
 def test_completion_upgrade_stack_selector_is_numeric(self):
  values=completion.complete(["upgrade",""])
  for item in [str(i) for i in range(8)]+["adopt","check","--offline","policy","--yes","--json"]:self.assertIn(item,values)
 def test_completion_upgrade_policy_stack_selector_is_numeric(self):
  values=completion.complete(["upgrade","policy",""])
  for i in range(8):self.assertIn(str(i),values)
 def test_completion_upgrade_adopt_has_no_stack_argument(self):
  values=completion.complete(["upgrade","adopt",""]);self.assertEqual([v for v in values if not v.startswith("--")],[]);self.assertIn("--json",values);self.assertIn("--yes",values)
 def test_completion_command_outputs_shell_integration(self):
  cp=self.run_cli("completion","bash");self.assertEqual(cp.returncode,0,cp.stderr);self.assertIn("complete -F _local_ai_complete local-ai ./local-ai",cp.stdout);self.assertIn("__complete",cp.stdout)
 def test_completion_rejects_unknown_shell(self):self.assertNotEqual(self.run_cli("completion","fish").returncode,0)
 def test_backup_help_is_owned_by_local_ai(self):
  cp=self.run_cli("backup","--help");self.assertEqual(cp.returncode,0,cp.stderr);self.assertIn("usage: local-ai backup",cp.stdout.lower());self.assertIn("--destination",cp.stdout);self.assertIn("--yes",cp.stdout);self.assertNotIn("backup-all.py",cp.stdout+cp.stderr)
 def test_noninteractive_backup_requires_yes(self):
  cp=self.run_cli("backup");self.assertEqual(cp.returncode,2);self.assertIn("CONFIRMATION_REQUIRED",cp.stderr)
 def test_json_backup_requires_yes_and_returns_json_error(self):
  cp=self.run_cli("--json","backup");self.assertEqual(cp.returncode,2);payload=json.loads(cp.stdout);self.assertEqual(payload["command"],"backup");self.assertEqual(payload["error"]["code"],"CONFIRMATION_REQUIRED");self.assertEqual(cp.stderr,"")
 def test_backup_yes_dispatches_to_structured_api(self):
  payload={"schema_version":"1","command":"backup","success":True,"result":{"path":"/backup/set","artifact_count":1}}
  with mock.patch.object(cli.backup,"backup_payload",return_value=payload) as run,mock.patch.object(cli.render,"render_cli"):rc=cli.main(["backup","--yes"])
  self.assertEqual(rc,0);run.assert_called_once_with(None)
 def test_backup_destination_reaches_structured_api(self):
  payload={"schema_version":"1","command":"backup","success":True,"result":{"path":"/backup/set","artifact_count":1}}
  with mock.patch.object(cli.backup,"backup_payload",return_value=payload) as run,mock.patch.object(cli.render,"render_cli"):rc=cli.main(["backup","--destination","/mnt/backup/local-ai","--yes"])
  self.assertEqual(rc,0);run.assert_called_once_with("/mnt/backup/local-ai")
 def test_json_backup_yes_is_rendered_by_public_cli(self):
  payload={"schema_version":"1","command":"backup","success":True,"result":{"path":"/backup/set","artifact_count":1}}
  with mock.patch.object(cli.backup,"backup_payload",return_value=payload) as run,mock.patch.object(cli.render,"render_json") as rendered:rc=cli.main(["--json","backup","--destination","/mnt/backup/local-ai","--yes"])
  self.assertEqual(rc,0);run.assert_called_once_with("/mnt/backup/local-ai");rendered.assert_called_once_with(payload)
 def test_restore_public_grammar_dispatches_to_structured_api(self):
  cases=((['plan','/backup/set'],'plan_payload',('/backup/set',),False),(['drill','/backup/set','--destination','/tmp/drill'],'drill_payload',('/backup/set','/tmp/drill'),True),(['apply','/backup/set','--check-clean-target'],'check_clean_target_payload',('/backup/set',),False),(['resume','/backup/set','--memory-sync-ssh-bootstrap','/ssh'],'resume_payload',('/backup/set','/ssh'),True))
  for public_args,name,expected,needs_yes in cases:
   payload={"schema_version":"1","command":"restore.test","success":True,"result":{}}
   with self.subTest(name=name),mock.patch.object(cli.restore,name,return_value=payload) as run,mock.patch.object(cli.render,"render_cli"):
    rc=cli.restore_command(public_args,cli.CLIContext(assume_yes=needs_yes));self.assertEqual(rc,0);run.assert_called_once_with(*expected)
 def test_restore_help_is_owned_by_local_ai_and_hides_private_scripts(self):
  for action in ("plan","drill","apply","resume","list-backup-sets"):
   cp=self.run_cli("restore",action,"--help");self.assertEqual(cp.returncode,0,cp.stderr);self.assertIn(f"usage: local-ai restore {action}",cp.stdout.lower())
   for private in ("restore-all.py","restore-drill.py","restore-live.py","restore-resume.py"):self.assertNotIn(private,cp.stdout+cp.stderr)
 def test_restore_without_action_shows_public_restore_help(self):
  cp=self.run_cli("restore");self.assertEqual(cp.returncode,0,cp.stderr)
  for item in ("list-backup-sets","plan","drill","apply","resume"):self.assertIn(item,cp.stdout)
 def test_json_list_backup_sets_has_public_versioned_contract(self):
  with tempfile.TemporaryDirectory() as tmp:cp=self.run_cli("restore","list-backup-sets","--json",env_extra={"DR_BACKUP_ROOT":tmp})
  self.assertEqual(cp.returncode,0,cp.stderr);payload=json.loads(cp.stdout);self.assertEqual(payload["command"],"restore.list-backup-sets");self.assertTrue(payload["success"]);self.assertEqual(payload["backup_sets"],[])
if __name__=="__main__":unittest.main()
