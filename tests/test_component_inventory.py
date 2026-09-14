# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Regression tests for manifest-owned component topology and rescans."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from commands import component_inventory, inventory, upgrade


class ComponentInventoryTests(unittest.TestCase):
    def test_manifests_classify_every_owned_container(self):
        components = component_inventory.compile_components()
        by_key = {f"{item['stack']}/{item['id']}": item for item in components}
        self.assertEqual(by_key["stack4/runner"]["management"]["type"], "local")
        self.assertEqual(by_key["stack6/sandbox"]["management"]["type"], "local")
        self.assertEqual(by_key["stack1/web"]["management"]["type"], "helper")
        self.assertEqual(by_key["stack6/sandbox-cleanup"]["management"]["type"], "helper")

    def test_upgrade_catalog_is_derived_from_manifest_metadata(self):
        catalog = component_inventory.compile_upgrade_catalog()
        expected = {
            f"{stack['id']}/{component['id']}"
            for stack in catalog["stacks"]
            for component in stack["components"]
        }
        self.assertEqual(set(upgrade.component_records()), expected)
        self.assertIn("stack4/runner", expected)
        self.assertIn("stack6/sandbox", expected)
        self.assertNotIn("stack1/web", expected)
        self.assertNotIn("stack6/sandbox-cleanup", expected)

    def test_rescan_snapshot_is_derived_metadata_not_runtime_authority(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            "os.environ", {"LOCAL_AI_RUNTIME_ROOT": tmp}, clear=False
        ):
            rc = inventory.main(["rescan"])
            self.assertEqual(rc, 0)
            snapshot = component_inventory.read_snapshot()
            self.assertIsNotNone(snapshot)
            self.assertTrue(snapshot["source_fingerprint"].startswith("sha256:"))
            self.assertTrue((Path(tmp) / "platform" / "component-inventory.json").is_file())

    def test_diff_reports_added_removed_and_changed_components(self):
        previous = {
            "components": [
                {"stack": "stack1", "id": "old", "management_type": "helper"},
                {"stack": "stack2", "id": "same", "management_type": "local"},
            ]
        }
        current = {
            "components": [
                {"stack": "stack2", "id": "same", "management_type": "versioned"},
                {"stack": "stack3", "id": "new", "management_type": "local"},
            ]
        }
        self.assertEqual(component_inventory.diff(previous, current), {
            "added": ["stack3/new"],
            "removed": ["stack1/old"],
            "changed": ["stack2/same"],
        })


if __name__ == "__main__":
    unittest.main()
