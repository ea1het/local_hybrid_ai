#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Contract tests for the persistent administrator override of selectable classification."""

from __future__ import annotations
import tempfile, unittest
from pathlib import Path
from unittest import mock
from local_ai_cli import upgrade
from local_ai_cli.upgrade import _policy as upgrade_policy
from local_ai_cli.upgrade import _selection as upgrade_selection


class UpgradeSelectableOverrideTests(unittest.TestCase):
    def _component(self, *, selectable=False):
        return upgrade.Component(
            stack="stack5",
            name="dockhand",
            service="dockhand",
            container="dockhand",
            compose="stack5_-_dockhand/docker-compose.yml",
            upstream="Finsys/dockhand",
            selectable=selectable,
        )

    def _record(self, *, has_apply=True):
        record = {
            "id": "dockhand",
            "stack": "stack5",
            "selectable": False,
            "default_policy": "major-series",
            "execution": {"mode": "inventory-only", "blocked_by": "executor-not-qualified"},
        }
        if has_apply:
            record["apply"] = {
                "type": "env-version",
                "env_key": "DOCKHAND_VERSION",
                "image_env_key": "DOCKHAND_REPOSITORY",
                "deploy": ["docker", "compose", "up", "-d", "dockhand"],
            }
        return record

    def test_not_selectable_component_without_override_is_rejected(self):
        component = self._component()
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(upgrade_selection.upgrade, "runtime_root", return_value=Path(tmp)),
            mock.patch.object(upgrade_selection, "component_record", return_value=self._record()),
        ):
            with self.assertRaises(upgrade.UpgradeError) as ctx:
                upgrade_selection.require_selection_permission(component)
        self.assertEqual(ctx.exception.code, "UPGRADE_COMPONENT_NOT_SELECTABLE")
        self.assertIn("upgrade selectable", str(ctx.exception))

    def test_persistent_override_enables_selection_permission(self):
        component = self._component()
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            upgrade_policy.set_selectable_override(runtime, "stack5/dockhand", True)
            with (
                mock.patch.object(upgrade_selection.upgrade, "runtime_root", return_value=runtime),
                mock.patch.object(upgrade_selection, "component_record", return_value=self._record()),
            ):
                upgrade_selection.require_selection_permission(component)

    def test_override_can_also_lock_a_manifest_selectable_component_closed(self):
        component = self._component(selectable=True)
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            upgrade_policy.set_selectable_override(runtime, "stack5/dockhand", False)
            with (
                mock.patch.object(upgrade_selection.upgrade, "runtime_root", return_value=runtime),
                mock.patch.object(upgrade_selection, "component_record", return_value=self._record()),
            ):
                with self.assertRaises(upgrade.UpgradeError) as ctx:
                    upgrade_selection.require_selection_permission(component)
            self.assertEqual(ctx.exception.code, "UPGRADE_COMPONENT_NOT_SELECTABLE")

    def test_clearing_override_restores_manifest_default(self):
        component = self._component()
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            upgrade_policy.set_selectable_override(runtime, "stack5/dockhand", True)
            upgrade_policy.clear_selectable_override(runtime, "stack5/dockhand")
            with (
                mock.patch.object(upgrade_selection.upgrade, "runtime_root", return_value=runtime),
                mock.patch.object(upgrade_selection, "component_record", return_value=self._record()),
            ):
                with self.assertRaises(upgrade.UpgradeError) as ctx:
                    upgrade_selection.require_selection_permission(component)
            self.assertEqual(ctx.exception.code, "UPGRADE_COMPONENT_NOT_SELECTABLE")

    def test_apply_recipe_available_reflects_manifest_wiring(self):
        self.assertTrue(upgrade_selection.apply_recipe_available(self._record(has_apply=True)))
        self.assertFalse(upgrade_selection.apply_recipe_available(self._record(has_apply=False)))

    def test_selection_status_respects_persistent_override(self):
        selection = {
            "stack": "stack5",
            "component": "dockhand",
            "current_at_selection": "v1.0.40",
            "version": "v1.0.48",
        }
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            before = upgrade_policy.selection_status(runtime, "stack5/dockhand", self._record(), selection)
            self.assertFalse(before["selection_valid"])
            upgrade_policy.set_selectable_override(runtime, "stack5/dockhand", True)
            after = upgrade_policy.selection_status(runtime, "stack5/dockhand", self._record(), selection)
            self.assertTrue(after["selection_valid"])

    def test_execution_records_patch_effective_selectable_for_selected_components_only(self):
        records = {
            "stack5/dockhand": self._record(),
            "stack2/rabbitmq": {
                "id": "rabbitmq",
                "stack": "stack2",
                "selectable": False,
                "execution": {"mode": "inventory-only", "blocked_by": "executor-not-qualified"},
            },
        }
        selections = [{"stack": "stack5", "component": "dockhand"}]
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            upgrade_policy.set_selectable_override(runtime, "stack5/dockhand", True)
            with (
                mock.patch.object(upgrade_selection.upgrade, "component_records", return_value=records),
                mock.patch.object(upgrade_selection.upgrade, "runtime_root", return_value=runtime),
            ):
                execution = upgrade_selection.execution_records_for(selections)
        self.assertTrue(execution["stack5/dockhand"]["selectable"])
        self.assertFalse(execution["stack2/rabbitmq"]["selectable"])
        self.assertFalse(records["stack5/dockhand"]["selectable"])


if __name__ == "__main__":
    unittest.main()
