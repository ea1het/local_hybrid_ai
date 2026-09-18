#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Every stack owns data construction while local-ai owns rendering."""
from __future__ import annotations
import unittest
from unittest import mock
from local_ai_cli import runtime_lifecycle
from local_ai_cli.common import stack_contracts
from local_ai_cli.install import engine as install_engine
class StackCliContractTests(unittest.TestCase):
 def test_every_manifest_stack_has_json_payload_contract(self):
  manifests=install_engine.all_manifests();self.assertEqual(sorted(manifests),list(range(8)))
  for sid,manifest in manifests.items():
   with self.subTest(stack=sid):
    payload=stack_contracts.json_payload(sid,manifest["directory"],probe=True);self.assertEqual(payload,{"stack":f"stack{sid}","probe":True})
 def test_stack_contracts_return_objects_not_serialized_text(self):
  for sid,manifest in install_engine.all_manifests().items():self.assertIsInstance(stack_contracts.json_payload(sid,manifest["directory"]),dict)
 def test_runtime_result_flows_through_stack_owned_contract(self):
  result=runtime_lifecycle.RuntimeResult("start",7,"stack7_-_open-webui",("open-webui",))
  with mock.patch("local_ai_cli.runtime_lifecycle.stack_contracts.json_payload",return_value={"stack":"stack7","success":True}) as builder:payload=result.as_dict()
  self.assertEqual(payload,{"stack":"stack7","success":True});builder.assert_called_once_with(7,"stack7_-_open-webui",schema_version="1",command="runtime.start",success=True,directory="stack7_-_open-webui",containers=["open-webui"])
if __name__=="__main__":unittest.main()
