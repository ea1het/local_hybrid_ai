# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Selection tests for compatibility policy and immutable registry target identity."""
from __future__ import annotations
import json,tempfile,unittest
from pathlib import Path
from unittest import mock
from local_ai_cli import upgrade
from local_ai_cli.upgrade import policy as upgrade_policy
from local_ai_cli.upgrade import registry as container_registry
from local_ai_cli.upgrade import selection as upgrade_selection
from local_ai_cli.upgrade import _core_impl as upgrade_core_impl
from local_ai_cli.upgrade import _entry_impl as upgrade_entry
class UpgradeSelectionPolicyTests(unittest.TestCase):
 def _runtime_patches(self,runtime):return (mock.patch.object(upgrade_selection.upgrade,"runtime_root",return_value=runtime),mock.patch.object(upgrade_selection.upgrade,"running_image",return_value="ghcr.io/open-webui/open-webui:v0.11.3"),mock.patch.object(upgrade_core_impl,"runtime_root",return_value=runtime),mock.patch.object(upgrade_core_impl,"running_image",return_value="ghcr.io/open-webui/open-webui:v0.11.3"))
 def _select(self,stack,name,version):return upgrade_entry.select_payload(stack,name,version)
 def test_select_persists_newer_target_inside_minor_series(self):
  digest="sha256:"+"a"*64
  with tempfile.TemporaryDirectory() as tmp:
   runtime=Path(tmp);p1,p2,p3,p4=self._runtime_patches(runtime)
   with p1,p2,p3,p4,mock.patch.object(container_registry,"manifest_probe",return_value=container_registry.RemoteProbe(digest,"ok")):payload=self._select("stack7",None,"v0.11.4")
   self.assertTrue(payload["success"]);selected=json.loads((runtime/"platform"/"upgrade-plan.json").read_text())["selected"]["stack7/open-webui"];self.assertEqual(selected["version"],"v0.11.4");self.assertEqual(selected["policy_at_selection"],"minor-series");self.assertEqual(selected["target_image"],"ghcr.io/open-webui/open-webui:v0.11.4");self.assertEqual(selected["target_digest"],digest)
 def test_select_rejects_target_outside_effective_policy(self):
  with tempfile.TemporaryDirectory() as tmp:
   runtime=Path(tmp);p1,p2,p3,p4=self._runtime_patches(runtime)
   with p1,p2,p3,p4,mock.patch.object(container_registry,"manifest_probe",return_value=container_registry.RemoteProbe("sha256:"+"b"*64,"ok")):
    with self.assertRaises(upgrade.UpgradeError) as ctx:self._select("stack7",None,"v0.12.0")
   self.assertEqual(ctx.exception.code,"UPGRADE_TARGET_UNSUPPORTED");self.assertFalse((runtime/"platform"/"upgrade-plan.json").exists())
 def test_select_rejects_target_missing_from_registry(self):
  with tempfile.TemporaryDirectory() as tmp:
   runtime=Path(tmp);p1,p2,p3,p4=self._runtime_patches(runtime)
   with p1,p2,p3,p4,mock.patch.object(container_registry,"manifest_probe",return_value=container_registry.RemoteProbe(None,"not_found")):
    with self.assertRaises(upgrade.UpgradeError) as ctx:self._select("stack7",None,"v0.11.99")
   self.assertEqual(ctx.exception.code,"UPGRADE_TARGET_NOT_AVAILABLE")
 def test_manual_override_allows_explicit_newer_target_outside_minor_series(self):
  with tempfile.TemporaryDirectory() as tmp:
   runtime=Path(tmp);upgrade_policy.set_override(runtime,"stack7/open-webui","manual");p1,p2,p3,p4=self._runtime_patches(runtime)
   with p1,p2,p3,p4,mock.patch.object(container_registry,"manifest_probe",return_value=container_registry.RemoteProbe("sha256:"+"c"*64,"ok")):payload=self._select("stack7",None,"v0.12.0")
   self.assertTrue(payload["success"]);self.assertEqual(json.loads((runtime/"platform"/"upgrade-plan.json").read_text())["selected"]["stack7/open-webui"]["policy_at_selection"],"manual")
 def test_apply_validation_rejects_a_tag_that_moved_after_selection(self):
  with tempfile.TemporaryDirectory() as tmp:
   runtime=Path(tmp);selection={"stack":"stack7","component":"open-webui","current_at_selection":"v0.11.3","version":"v0.11.4","policy_at_selection":"minor-series","target_image":"ghcr.io/open-webui/open-webui:v0.11.4","target_digest":"sha256:"+"a"*64};p1,p2,p3,p4=self._runtime_patches(runtime)
   with p1,p2,p3,p4,mock.patch.object(container_registry,"manifest_probe",return_value=container_registry.RemoteProbe("sha256:"+"d"*64,"ok")):
    with self.assertRaises(upgrade.UpgradeError) as ctx:upgrade_selection.validate_selected_baselines([selection])
   self.assertEqual(ctx.exception.code,"UPGRADE_TARGET_MOVED")
if __name__=="__main__":unittest.main()
