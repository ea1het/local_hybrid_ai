# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Contracts for the structured recovery API used by the public CLI."""
from __future__ import annotations

import unittest
from unittest import mock

from commands.recovery import public_api


class RecoveryStructuredApiTests(unittest.TestCase):
    def test_plan_returns_serializable_public_envelope_without_rendering(self):
        plan = mock.Mock()
        plan.as_dict.return_value = {"kind": "local-hybrid-ai-restore-plan", "changes_made": False}
        engine = mock.Mock()
        engine.plan_restore_all.return_value = plan
        with mock.patch.object(public_api, "_load", return_value=engine):
            payload = public_api.plan_payload("/backup/set")
        self.assertEqual(payload["schema_version"], "1")
        self.assertEqual(payload["command"], "restore.plan")
        self.assertTrue(payload["success"])
        self.assertFalse(payload["result"]["changes_made"])
        engine.plan_restore_all.assert_called_once()

    def test_drill_returns_serializable_public_envelope_without_rendering(self):
        result = mock.Mock()
        result.as_dict.return_value = {
            "destination": "/tmp/drill",
            "live_runtime_modified": False,
            "ports_published": False,
            "platform_network_attached": False,
        }
        engine = mock.Mock()
        engine.run_restore_drill.return_value = result
        with mock.patch.object(public_api, "_load", return_value=engine):
            payload = public_api.drill_payload("/backup/set", "/tmp/drill")
        self.assertEqual(payload["schema_version"], "1")
        self.assertEqual(payload["command"], "restore.drill")
        self.assertTrue(payload["success"])
        self.assertFalse(payload["result"]["live_runtime_modified"])
        engine.run_restore_drill.assert_called_once()

    def test_adapter_contains_no_rendering_or_subprocess_boundary(self):
        source = (public_api.RECOVERY_ROOT / "public_api.py").read_text(encoding="utf-8")
        self.assertNotIn("subprocess", source)
        self.assertNotIn("render_json", source)
        self.assertNotIn("json.dumps", source)
        self.assertNotIn("print(", source)


if __name__ == "__main__":
    unittest.main()
