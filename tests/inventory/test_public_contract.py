# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Inventory command mutation-boundary contracts."""
from __future__ import annotations
import unittest
from unittest import mock
from commands import inventory
class InventoryPublicContractTests(unittest.TestCase):
 def _snapshot(self):return {"source_fingerprint":"abc123","components":[]}
 def test_bare_inventory_never_writes_snapshot(self):
  current=self._snapshot()
  with mock.patch.object(inventory.api.component_inventory,"read_snapshot",return_value=None),mock.patch.object(inventory.api.component_inventory,"snapshot",return_value=current),mock.patch.object(inventory.api.component_inventory,"diff",return_value={"added":[],"removed":[],"changed":[]}),mock.patch.object(inventory.api.component_inventory,"write_snapshot") as write:payload=inventory.json_payload([])
  self.assertTrue(payload["success"]);self.assertFalse(payload["snapshot_written"]);write.assert_not_called()
 def test_rescan_writes_snapshot(self):
  current=self._snapshot()
  with mock.patch.object(inventory.api.component_inventory,"read_snapshot",return_value=None),mock.patch.object(inventory.api.component_inventory,"snapshot",return_value=current),mock.patch.object(inventory.api.component_inventory,"diff",return_value={"added":[],"removed":[],"changed":[]}),mock.patch.object(inventory.api.component_inventory,"write_snapshot") as write:payload=inventory.json_payload(["rescan"])
  self.assertTrue(payload["success"]);write.assert_called_once_with(current)
 def test_usage_error(self):self.assertEqual(inventory.json_payload(["unexpected"])["error"]["code"],"INVENTORY_USAGE")
 def test_inventory_uses_private_component_implementation(self):self.assertEqual(inventory.api.component_inventory.__name__,"commands.inventory.component_inventory")
if __name__=="__main__":unittest.main()
