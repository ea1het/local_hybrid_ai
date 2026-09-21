#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Contracts for package-owned Backup/Restore structured APIs."""

from __future__ import annotations
import unittest
from pathlib import Path
from unittest import mock
from local_ai_cli import backup, cli, restore
from local_ai_cli.backup import api as backup_api
from local_ai_cli.restore import api as restore_api

ROOT = Path(__file__).resolve().parents[1]


class RecoveryStructuredApiTests(unittest.TestCase):
    def test_backup_returns_serializable_public_envelope_without_rendering(self):
        result = mock.Mock()
        result.as_dict.return_value = {"path": "/backup/set", "artifact_count": 3}
        dr = mock.Mock()
        dr.resolve_backup_root.return_value = ("/backup", None)
        engine = mock.Mock()
        engine.execute_backup_all.return_value = result
        with mock.patch.object(backup_api, "_load", side_effect=[dr, engine]):
            payload = backup.backup_payload("/backup")
        self.assertEqual(payload["command"], "backup")
        self.assertTrue(payload["success"])
        self.assertEqual(payload["result"]["artifact_count"], 3)

    def test_plan_returns_serializable_public_envelope_without_rendering(self):
        plan = mock.Mock()
        plan.as_dict.return_value = {"kind": "local-hybrid-ai-restore-plan", "changes_made": False}
        engine = mock.Mock()
        engine.plan_restore_all.return_value = plan
        with mock.patch.object(restore_api, "_load", return_value=engine):
            payload = restore.plan_payload("/backup/set")
        self.assertEqual(payload["command"], "restore.plan")
        self.assertTrue(payload["success"])

    def test_plan_failure_is_stable_public_envelope(self):
        engine = mock.Mock()
        engine.plan_restore_all.side_effect = ValueError("bad recovery point")
        with mock.patch.object(restore_api, "_load", return_value=engine):
            payload = restore.plan_payload("/backup/set")
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"]["code"], "RESTORE_PLAN_FAILED")

    def test_drill_returns_serializable_public_envelope_without_rendering(self):
        result = mock.Mock()
        result.as_dict.return_value = {"destination": "/tmp/drill"}
        engine = mock.Mock()
        engine.run_restore_drill.return_value = result
        with mock.patch.object(restore_api, "_load", return_value=engine):
            payload = restore.drill_payload("/backup/set", "/tmp/drill")
        self.assertTrue(payload["success"])

    def test_clean_target_preflight_uses_importable_service(self):
        service = mock.Mock()
        service.check_clean.return_value = {"clean_target": True, "changes_made": False}
        with mock.patch.object(restore_api, "_load", return_value=service) as load:
            payload = restore.check_clean_target_payload("/backup/set")
        load.assert_called_once_with("_restore_live_service")
        self.assertTrue(payload["success"])

    def test_live_apply_failure_is_stable_public_envelope(self):
        service = mock.Mock()
        service.execute.side_effect = OSError("restore failed")
        with mock.patch.object(restore_api, "_load", return_value=service):
            payload = restore.apply_payload("/backup/set")
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"]["code"], "RESTORE_APPLY_FAILED")

    def test_resume_uses_importable_engine(self):
        engine = mock.Mock()
        engine.resume.return_value = {"status": "PASS", "memory_sync_enabled": True}
        with mock.patch.object(restore_api, "_load", return_value=engine) as load:
            payload = restore.resume_payload("/backup/set", "/operator/ssh")
        load.assert_called_once_with("_restore_resume")
        self.assertTrue(payload["success"])

    def test_failed_payload_has_human_error_text(self):
        text = restore.cli_text(
            {
                "schema_version": "1",
                "command": "restore.resume",
                "success": False,
                "error": {"code": "RESTORE_RESUME_FAILED", "message": "broken"},
            }
        )
        self.assertEqual(text, "RECOVERY ERROR [RESTORE_RESUME_FAILED]: broken")

    def test_plan_public_dispatch_uses_restore_package(self):
        payload = {"schema_version": "1", "command": "restore.plan", "success": True, "result": {"changes_made": False}}
        with (
            mock.patch.object(cli.restore, "plan_payload", return_value=payload) as run,
            mock.patch.object(cli.render, "render_json"),
        ):
            rc = cli.restore_command(["plan", "/backup/set"], cli.CLIContext(json_output=True))
        self.assertEqual(rc, 0)
        run.assert_called_once_with("/backup/set")

    def test_public_dispatcher_has_no_recovery_facade_or_private_subprocess_boundary(self):
        source = (ROOT / "src" / "local_ai_cli" / "cli.py").read_text(encoding="utf-8")
        self.assertNotIn("local_ai_cli.recovery", source)
        self.assertNotIn("recovery_api", source)
        self.assertNotIn("_run_internal", source)
        self.assertNotIn("subprocess", source)

    def test_owned_apis_contain_no_rendering_or_subprocess_boundary(self):
        for path in (backup_api.PACKAGE_ROOT / "api.py", restore_api.RESTORE_ROOT / "api.py"):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("subprocess", source)
            self.assertNotIn("render_json", source)
            self.assertNotIn("print(", source)


if __name__ == "__main__":
    unittest.main()
