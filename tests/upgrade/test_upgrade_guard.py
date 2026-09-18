#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Concurrency and failure-journal tests for destructive upgrade application."""
from __future__ import annotations
import fcntl,json,os,tempfile,unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock
from local_ai_cli.upgrade import guard as upgrade_guard
class UpgradeGuardTests(unittest.TestCase):
 def test_non_apply_commands_are_not_locked(self):
  called=[];rc=upgrade_guard.run_guarded(["upgrade","check"],lambda:called.append(True) or 0);self.assertEqual(rc,0);self.assertEqual(called,[True])
 def test_apply_detection_is_position_independent_for_global_flags(self):
  for argv in (["upgrade","--yes"],["--yes","upgrade"],["--json","upgrade","--yes"],["upgrade","--json","--yes"],["--yes","upgrade","--json"]):self.assertTrue(upgrade_guard._is_upgrade_apply(list(argv)),argv)
  for argv in (["upgrade"],["upgrade","check","--yes"],["upgrade","policy","7","--yes"]):self.assertFalse(upgrade_guard._is_upgrade_apply(list(argv)),argv)
 def test_concurrent_upgrade_fails_closed(self):
  with tempfile.TemporaryDirectory() as tmp,mock.patch.dict(os.environ,{"LOCAL_AI_RUNTIME_ROOT":tmp}):
   platform=Path(tmp)/"platform";platform.mkdir(parents=True);lock_path=platform/"upgrade.lock"
   with lock_path.open("a+") as held:
    fcntl.flock(held.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB);output=StringIO()
    with redirect_stdout(output):rc=upgrade_guard.run_guarded(["--yes","upgrade","--json"],lambda:0)
    payload=json.loads(output.getvalue())
   self.assertEqual(rc,1);self.assertEqual(payload["error"]["code"],"UPGRADE_BUSY")
 def test_failed_apply_is_journaled_with_selection_and_error_code(self):
  with tempfile.TemporaryDirectory() as tmp,mock.patch.dict(os.environ,{"LOCAL_AI_RUNTIME_ROOT":tmp}):
   platform=Path(tmp)/"platform";platform.mkdir(parents=True);(platform/"upgrade-plan.json").write_text(json.dumps({"schema_version":1,"selected":{"stack6/hermes":{"stack":"stack6","component":"hermes","current_at_selection":"v1","version":"v2"}}}),encoding="utf-8")
   def failing_main():print(json.dumps({"schema_version":"1","success":False,"error":{"code":"UPGRADE_TARGET_NOT_AVAILABLE","message":"missing"}}));return 1
   output=StringIO()
   with redirect_stdout(output):rc=upgrade_guard.run_guarded(["--json","upgrade","--yes"],failing_main)
   event=json.loads((platform/"upgrade-history.jsonl").read_text(encoding="utf-8").splitlines()[-1]);self.assertEqual(rc,1);self.assertFalse(event["success"]);self.assertEqual(event["error_code"],"UPGRADE_TARGET_NOT_AVAILABLE");self.assertEqual(event["selected"][0]["component"],"hermes");self.assertEqual(event["stage"],"apply")
if __name__=="__main__":unittest.main()
