#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Inventory command mutation-boundary contracts."""
from __future__ import annotations
import unittest
from unittest import mock
from local_ai_cli import inventory
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
 def test_inventory_uses_private_component_implementation(self):self.assertEqual(inventory.api.component_inventory.__name__,"local_ai_cli.inventory.component_inventory")
 def test_cli_text_renders_the_component_table(self):
  payload={"success":True,"source_fingerprint":"sha256:abc","components":[{"stack":"stack2","id":"redis","management_type":"versioned","service":"firecrawl-redis","container":"firecrawl-redis","upgrade_visible":True},{"stack":"stack0","id":"platform-foundation","management_type":"platform","service":None,"container":None,"upgrade_visible":True}],"previous_snapshot":True,"snapshot_written":False,"changes":{"added":[],"removed":[],"changed":["stack2/redis"]}}
  text=inventory.cli_text(payload)
  self.assertIn("STACK",text);self.assertIn("CONTAINER",text);self.assertIn("2 ",text);self.assertIn("firecrawl-redis",text);self.assertIn("platform-foundation",text);self.assertIn("-",text)
  self.assertIn("SOURCE FINGERPRINT  sha256:abc",text);self.assertIn("CHANGED  stack2/redis",text)
 def test_cli_text_reports_error_without_a_table(self):
  payload={"success":False,"error":{"code":"INVENTORY_INVALID","message":"boom"}}
  self.assertEqual(inventory.cli_text(payload),"INVENTORY ERROR [INVENTORY_INVALID]: boom")
if __name__=="__main__":unittest.main()
