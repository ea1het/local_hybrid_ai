# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Public inventory mutation-boundary contracts."""
from __future__ import annotations

import unittest
from unittest import mock

from commands import inventory


class InventoryPublicContractTests(unittest.TestCase):
    def _snapshot(self):
        return {"source_fingerprint": "abc123", "components": {"stack0/foundation": {}}}

    def test_bare_inventory_never_writes_snapshot(self):
        current = self._snapshot()
        with mock.patch.object(inventory.component_inventory, "read_snapshot", return_value=None), \
             mock.patch.object(inventory.component_inventory, "snapshot", return_value=current), \
             mock.patch.object(inventory.component_inventory, "diff", return_value={"added": [], "removed": [], "changed": []}), \
             mock.patch.object(inventory.component_inventory, "write_snapshot") as write:
            payload = inventory.json_payload([])
        self.assertTrue(payload["success"])
        self.assertEqual(payload["command"], "inventory")
        self.assertFalse(payload["snapshot_written"])
        write.assert_not_called()

    def test_rescan_explicitly_writes_snapshot(self):
        current = self._snapshot()
        with mock.patch.object(inventory.component_inventory, "read_snapshot", return_value=None), \
             mock.patch.object(inventory.component_inventory, "snapshot", return_value=current), \
             mock.patch.object(inventory.component_inventory, "diff", return_value={"added": [], "removed": [], "changed": []}), \
             mock.patch.object(inventory.component_inventory, "write_snapshot") as write:
            payload = inventory.json_payload(["rescan"])
        self.assertTrue(payload["success"])
        self.assertEqual(payload["command"], "inventory.rescan")
        self.assertTrue(payload["snapshot_written"])
        write.assert_called_once_with(current)

    def test_unknown_inventory_arguments_are_usage_error_payload(self):
        payload = inventory.json_payload(["unexpected"])
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"]["code"], "INVENTORY_USAGE")
        self.assertIn("inventory [rescan]", payload["error"]["message"])


if __name__ == "__main__":
    unittest.main()
