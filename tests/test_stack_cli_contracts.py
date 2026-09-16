# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Every stack owns data construction while local-ai owns rendering."""
from __future__ import annotations
import unittest
from commands import install,stack_contracts
class StackCliContractTests(unittest.TestCase):
 def test_every_manifest_stack_has_json_payload_contract(self):
  manifests=install.all_manifests()
  self.assertEqual(sorted(manifests),list(range(8)))
  for sid,manifest in manifests.items():
   with self.subTest(stack=sid):
    payload=stack_contracts.json_payload(sid,manifest["directory"],probe=True)
    self.assertEqual(payload,{"stack":f"stack{sid}","probe":True})
 def test_stack_contracts_return_objects_not_serialized_text(self):
  for sid,manifest in install.all_manifests().items():
   self.assertIsInstance(stack_contracts.json_payload(sid,manifest["directory"]),dict)
if __name__=="__main__":unittest.main()
