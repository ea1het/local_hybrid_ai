# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Contract tests for explicit administrator override of upgrade qualification."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from commands import upgrade, upgrade_entry, upgrade_policy


class UpgradeForceOverrideTests(unittest.TestCase):
    def _component(self, *, selectable: bool = False):
        return upgrade.Component(
            stack="stack5",
            name="dockhand",
            service="dockhand",
            container="dockhand",
            compose="stack5_-_dockhand/docker-compose.yml",
            upstream="Finsys/dockhand",
            selectable=selectable,
        )

    def _record(self, *, force_capable: bool = True):
        record = {
            "id": "dockhand",
            "stack": "stack5",
            "selectable": False,
            "default_policy": "major-series",
            "execution": {"mode": "inventory-only", "blocked_by": "executor-not-qualified"},
        }
        if force_capable:
            record["apply"] = {
                "type": "env-version",
                "env_key": "DOCKHAND_VERSION",
                "image_env_key": "DOCKHAND_REPOSITORY",
                "deploy": ["docker", "compose", "up", "-d", "dockhand"],
            }
        return record

    def test_inventory_only_component_requires_explicit_force(self):
        component = self._component()
        with mock.patch("commands.upgrade_entry._component_record", return_value=self._record()):
            with self.assertRaises(upgrade.UpgradeError) as ctx:
                upgrade_entry._require_selection_permission(component, force=False)
        self.assertEqual(ctx.exception.code, "UPGRADE_COMPONENT_NOT_SELECTABLE")
        self.assertIn("--force", str(ctx.exception))

    def test_force_accepts_unqualified_component_with_deterministic_recipe(self):
        component = self._component()
        with mock.patch("commands.upgrade_entry._component_record", return_value=self._record()):
            forced, blocked_by = upgrade_entry._require_selection_permission(component, force=True)
        self.assertTrue(forced)
        self.assertEqual(blocked_by, "executor-not-qualified")

    def test_force_does_not_invent_missing_mutation_recipe(self):
        component = self._component()
        with mock.patch("commands.upgrade_entry._component_record", return_value=self._record(force_capable=False)):
            with self.assertRaises(upgrade.UpgradeError) as ctx:
                upgrade_entry._require_selection_permission(component, force=True)
        self.assertEqual(ctx.exception.code, "UPGRADE_FORCE_UNAVAILABLE")

    def test_forced_inventory_selection_is_policy_valid(self):
        selection = {
            "stack": "stack5",
            "component": "dockhand",
            "current_at_selection": "v1.0.40",
            "version": "v1.0.48",
            "forced": True,
            "qualification_bypassed": "executor-not-qualified",
        }
        with tempfile.TemporaryDirectory() as tmp:
            status = upgrade_policy.selection_status(
                Path(tmp),
                "stack5/dockhand",
                self._record(),
                selection,
            )
        self.assertTrue(status["selection_valid"])

    def test_unforced_inventory_selection_is_not_policy_valid(self):
        selection = {
            "stack": "stack5",
            "component": "dockhand",
            "current_at_selection": "v1.0.40",
            "version": "v1.0.48",
        }
        with tempfile.TemporaryDirectory() as tmp:
            status = upgrade_policy.selection_status(
                Path(tmp),
                "stack5/dockhand",
                self._record(),
                selection,
            )
        self.assertFalse(status["selection_valid"])

    def test_execution_view_authorizes_only_explicit_forced_selection(self):
        records = {
            "stack5/dockhand": self._record(),
            "stack2/rabbitmq": {
                "id": "rabbitmq",
                "stack": "stack2",
                "selectable": False,
                "execution": {"mode": "inventory-only", "blocked_by": "executor-not-qualified"},
            },
        }
        selections = [{"stack": "stack5", "component": "dockhand", "forced": True}]
        with mock.patch("commands.upgrade_entry.upgrade.component_records", return_value=records):
            execution = upgrade_entry._execution_records_for(selections)
        self.assertTrue(execution["stack5/dockhand"]["selectable"])
        self.assertFalse(execution["stack2/rabbitmq"]["selectable"])
        self.assertFalse(records["stack5/dockhand"]["selectable"])


if __name__ == "__main__":
    unittest.main()
