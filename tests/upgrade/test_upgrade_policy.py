# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Compatibility-policy tests for project defaults and installation overrides.

These tests define the three supported policy modes, monotonic version rules,
installation-local override persistence/clear behaviour, and the requirement that
policy changes invalidate incompatible selections without silently deleting them.
They do not perform registry discovery or execute upgrades.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from commands import upgrade, upgrade_policy


class UpgradePolicyTests(unittest.TestCase):
    def test_minor_series_accepts_only_newer_same_major_minor(self):
        self.assertTrue(upgrade_policy.target_supported("minor-series", "1.27.1", "1.27.3"))
        self.assertFalse(upgrade_policy.target_supported("minor-series", "1.27.1", "1.28.0"))
        self.assertFalse(upgrade_policy.target_supported("minor-series", "1.27.3", "1.27.2"))

    def test_major_series_accepts_newer_same_major(self):
        self.assertTrue(upgrade_policy.target_supported("major-series", "17.10", "17.11"))
        self.assertTrue(upgrade_policy.target_supported("major-series", "v2026.8.31", "v2026.9.11"))
        self.assertFalse(upgrade_policy.target_supported("major-series", "17.10", "18.0"))

    def test_manual_uses_explicit_target_without_series_inference(self):
        self.assertTrue(upgrade_policy.target_supported("manual", "1.27.1", "1.28.0"))
        self.assertTrue(upgrade_policy.target_supported("manual", "latest(aaaaaaaaa)", "latest(bbbbbbbbb)"))
        self.assertFalse(upgrade_policy.target_supported("manual", "1.28.0", "1.27.9"))
        self.assertFalse(upgrade_policy.target_supported("manual", "1.27.1", "1.27.1"))

    def test_dockhand_default_policy_is_major_series(self):
        self.assertEqual(upgrade.component_records()["stack5/dockhand"]["default_policy"], "major-series")

    def test_override_is_installation_local_and_clear_restores_default(self):
        component = {"stack": "stack4", "id": "gitea", "default_policy": "minor-series"}
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            self.assertEqual(
                upgrade_policy.effective_policy(runtime, "stack4/gitea", component),
                ("minor-series", None, "minor-series"),
            )
            upgrade_policy.set_override(runtime, "stack4/gitea", "manual")
            self.assertEqual(
                upgrade_policy.effective_policy(runtime, "stack4/gitea", component),
                ("minor-series", "manual", "manual"),
            )
            state = json.loads((runtime / "platform" / "upgrade-policy.json").read_text())
            self.assertEqual(state["overrides"], {"stack4/gitea": "manual"})
            upgrade_policy.clear_override(runtime, "stack4/gitea")
            self.assertEqual(
                upgrade_policy.effective_policy(runtime, "stack4/gitea", component),
                ("minor-series", None, "minor-series"),
            )

    def test_policy_change_marks_existing_selection_invalid_without_clearing_it(self):
        component = {
            "stack": "stack4",
            "id": "gitea",
            "selectable": True,
            "default_policy": "major-series",
        }
        selection = {"current_at_selection": "1.27.1", "version": "1.28.0"}
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            before = upgrade_policy.selection_status(runtime, "stack4/gitea", component, selection)
            self.assertTrue(before["selection_valid"])
            upgrade_policy.set_override(runtime, "stack4/gitea", "minor-series")
            after = upgrade_policy.selection_status(runtime, "stack4/gitea", component, selection)
            self.assertFalse(after["selection_valid"])
            self.assertEqual(selection["version"], "1.28.0")


if __name__ == "__main__":
    unittest.main()
