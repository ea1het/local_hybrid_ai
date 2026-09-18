#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Install command boundary tests."""
import unittest
from unittest.mock import patch
from local_ai_cli.install import api,engine
class InstallApiTests(unittest.TestCase):
 def _mocks(self,actions):
  return patch.multiple(engine,preflight=unittest.mock.DEFAULT,all_manifests=unittest.mock.DEFAULT,load_lifecycle=unittest.mock.DEFAULT,validate_registry=unittest.mock.DEFAULT,resolve_requested=unittest.mock.DEFAULT,resolve_plan=unittest.mock.DEFAULT,build_actions=unittest.mock.DEFAULT)
 def test_package_is_self_contained(self):
  self.assertEqual(api.engine.__name__,"local_ai_cli.install.engine");self.assertNotIn("local_ai_cli.installer",api.__dict__.values())
 def test_execute_requires_semantic_consent(self):
  action=engine.Action(0,"stack0_-_platform","verify",("./verify.sh",),"test")
  with patch.object(engine,"preflight"),patch.object(engine,"all_manifests",return_value={0:{"id":0,"directory":"stack0_-_platform"}}),patch.object(engine,"load_lifecycle",return_value={"stacks":{"0":{"directory":"stack0_-_platform","required_containers":[],"prepare":[],"deploy":[],"reconcile":[],"verify":[]}}}),patch.object(engine,"validate_registry"),patch.object(engine,"resolve_requested",return_value=[0]),patch.object(engine,"resolve_plan",return_value=[0]),patch.object(engine,"build_actions",return_value=([action],[],set())),patch.object(engine,"execute") as execute:payload,rc=api.build_payload(["0"])
  self.assertEqual(rc,2);self.assertEqual(payload["error"]["code"],"CONFIRMATION_REQUIRED");execute.assert_not_called()
 def test_plan_is_read_only(self):
  with patch.object(engine,"preflight"),patch.object(engine,"all_manifests",return_value={0:{"id":0,"directory":"stack0_-_platform"}}),patch.object(engine,"load_lifecycle",return_value={"stacks":{"0":{"directory":"stack0_-_platform","required_containers":[],"prepare":[],"deploy":[],"reconcile":[],"verify":[]}}}),patch.object(engine,"validate_registry"),patch.object(engine,"resolve_requested",return_value=[0]),patch.object(engine,"resolve_plan",return_value=[0]),patch.object(engine,"build_actions",return_value=([],[],set())),patch.object(engine,"execute") as execute:payload,rc=api.build_payload(["0","--plan"])
  self.assertEqual(rc,0);self.assertTrue(payload["success"]);execute.assert_not_called()
 def test_yes_executes_directly_without_private_cli(self):
  lifecycle={"stacks":{"0":{"directory":"stack0_-_platform","required_containers":[],"prepare":[],"deploy":[],"reconcile":[],"verify":[]}}};action=engine.Action(0,"stack0_-_platform","verify",("./verify.sh",),"test")
  with patch.object(engine,"preflight"),patch.object(engine,"all_manifests",return_value={0:{"id":0,"directory":"stack0_-_platform"}}),patch.object(engine,"load_lifecycle",return_value=lifecycle),patch.object(engine,"validate_registry"),patch.object(engine,"resolve_requested",return_value=[0]),patch.object(engine,"resolve_plan",return_value=[0]),patch.object(engine,"build_actions",return_value=([action],[],set())),patch.object(engine,"execute") as execute:payload,rc=api.build_payload(["0"],assume_yes=True)
  self.assertEqual(rc,0);self.assertTrue(payload["executed"]);execute.assert_called_once_with([action],lifecycle)
if __name__=="__main__":unittest.main()
