# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Install command boundary tests."""
import unittest
from unittest.mock import patch
from commands.install import api
from commands import installer
class InstallApiTests(unittest.TestCase):
 def test_install_package_does_not_reexport_installer_primitives(self):
  import commands.install as install
  self.assertFalse(hasattr(install,"all_manifests"));self.assertFalse(hasattr(install,"InstallerError"))
 def test_execute_requires_semantic_consent(self):
  action=installer.Action(0,"stack0_-_platform","verify",("./verify.sh",),"test")
  with patch.object(installer,"preflight"),patch.object(installer,"all_manifests",return_value={0:{"id":0,"directory":"stack0_-_platform"}}),patch.object(installer,"load_lifecycle",return_value={"stacks":{"0":{"directory":"stack0_-_platform","required_containers":[],"prepare":[],"deploy":[],"reconcile":[],"verify":[]}}}),patch.object(installer,"validate_registry"),patch.object(installer,"resolve_requested",return_value=[0]),patch.object(installer,"resolve_plan",return_value=[0]),patch.object(installer,"build_actions",return_value=([action],[],set())):
   payload,rc=api.build_payload(["0"])
  self.assertEqual(rc,2);self.assertEqual(payload["error"]["code"],"CONFIRMATION_REQUIRED")
 def test_plan_is_read_only_without_consent(self):
  with patch.object(installer,"preflight"),patch.object(installer,"all_manifests",return_value={0:{"id":0,"directory":"stack0_-_platform"}}),patch.object(installer,"load_lifecycle",return_value={"stacks":{"0":{"directory":"stack0_-_platform","required_containers":[],"prepare":[],"deploy":[],"reconcile":[],"verify":[]}}}),patch.object(installer,"validate_registry"),patch.object(installer,"resolve_requested",return_value=[0]),patch.object(installer,"resolve_plan",return_value=[0]),patch.object(installer,"build_actions",return_value=([],[],set())):
   payload,rc=api.build_payload(["0","--plan"])
  self.assertEqual(rc,0);self.assertTrue(payload["success"]);self.assertFalse(payload["executed"])
if __name__=="__main__":unittest.main()
