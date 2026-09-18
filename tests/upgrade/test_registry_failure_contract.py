# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Deterministic fail-closed tests for package-owned registry failures."""
from __future__ import annotations
import unittest
from unittest import mock
from commands.upgrade import _core_impl as upgrade
from commands.upgrade import registry as upgrade_registry
class RegistryFailureContractTests(unittest.TestCase):
 def test_http_failure_classification_is_stable(self):
  self.assertEqual(upgrade_registry._classify_http_status(429),"rate_limited");self.assertEqual(upgrade_registry._classify_http_status(401),"unauthorized");self.assertEqual(upgrade_registry._classify_http_status(403),"forbidden")
 def test_registry_tags_preserve_rate_limit_and_auth_failures(self):
  for status,expected in ((429,"rate_limited"),(401,"unauthorized"),(403,"forbidden")):
   with self.subTest(status=status),mock.patch("commands.upgrade.registry._registry_request",return_value=(status,{},b"")):
    probe=upgrade_registry.registry_tags("redis:alpine");self.assertEqual(probe.tags,());self.assertEqual(probe.status,expected)
 def test_manifest_probe_preserves_rate_limit_and_auth_failures(self):
  for status,expected in ((429,"rate_limited"),(401,"unauthorized"),(403,"forbidden")):
   with self.subTest(status=status),mock.patch("commands.upgrade.registry._registry_request",return_value=(status,{},b"")):
    probe=upgrade_registry.manifest_probe("redis:alpine");self.assertIsNone(probe.digest);self.assertEqual(probe.status,expected)
 def test_inventory_never_renders_registry_failure_as_current(self):
  component=upgrade.Component(stack="stack1",name="haproxy",service=None,container="haproxy",compose=None,upstream="haproxy/haproxy",selectable=False);record={"stack":"stack1","id":"haproxy"}
  for status in ("rate_limited","unauthorized","forbidden"):
   state=upgrade_registry.RegistryState(image="haproxy:3.0-alpine",local_digest="sha256:local",remote_digest=None,tracking_image="haproxy:3.0-alpine",remote_status=status,tags_status=status,registry="docker.io",repository="library/haproxy")
   with self.subTest(status=status),mock.patch.dict("os.environ",{"LOCAL_AI_REGISTRY_CACHE_TTL_SECONDS":"0"}),mock.patch.object(upgrade,"load_catalog",return_value=[component]),mock.patch.object(upgrade,"component_records",return_value={"stack1/haproxy":record}),mock.patch.object(upgrade,"read_env",return_value={}),mock.patch.object(upgrade,"load_plan",return_value={"schema_version":1,"selected":{}}),mock.patch.object(upgrade,"running_image",return_value="haproxy:3.0-alpine"),mock.patch.object(upgrade.upgrade_registry,"inspect",return_value=state):
    rows=upgrade.inventory(query_upstream=True);self.assertEqual(rows[0]["available"],"unknown");self.assertNotEqual(upgrade._human_available(rows[0]),"current");self.assertEqual(rows[0]["registry"]["remote_status"],status)
if __name__=="__main__":unittest.main()
