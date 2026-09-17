# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Protect the single-source invariant for container version discovery."""
from __future__ import annotations
import unittest
from unittest import mock
from commands.upgrade import component_inventory
from commands.upgrade import _core_impl as upgrade
from commands.upgrade import registry as container_registry
class VersionSourceTests(unittest.TestCase):
 def _inventory_component(self):return upgrade.Component(stack="stack1",name="haproxy",service=None,container="haproxy",compose=None,upstream="haproxy/haproxy",selectable=False)
 def _inventory(self,component,record,image,*,online=True,registry_state=None):
  records={f"{component.stack}/{component.name}":record}
  with mock.patch.dict("os.environ",{"LOCAL_AI_REGISTRY_CACHE_TTL_SECONDS":"0"}),mock.patch.object(upgrade,"load_catalog",return_value=[component]),mock.patch.object(upgrade,"component_records",return_value=records),mock.patch.object(upgrade,"read_env",return_value={}),mock.patch.object(upgrade,"load_plan",return_value={"schema_version":1,"selected":{}}),mock.patch.object(upgrade,"running_image",return_value=image),mock.patch.object(upgrade.upgrade_registry,"inspect",return_value=registry_state) as registry:return upgrade.inventory(query_upstream=online),registry
 def test_manifest_upgrade_metadata_uses_no_lateral_version_sources(self):
  catalog=component_inventory.compile_upgrade_catalog();components=[c for s in catalog["stacks"] for c in s["components"]];self.assertFalse(any("version_source" in c for c in components));self.assertFalse(any("registry_source" in c for c in components))
 def test_inventory_reports_registry_human_version_update(self):
  state=container_registry.RegistryState(image="haproxy:3.0-alpine",local_digest="sha256:old",remote_digest="sha256:new",tracking_image="haproxy:3.0-alpine",remote_status="ok",current_version="3.0.18-alpine",available_version="3.0.19-alpine",tags_status="ok",registry="docker.io",repository="library/haproxy");rows,_=self._inventory(self._inventory_component(),{"stack":"stack1","id":"haproxy"},"haproxy:3.0-alpine",registry_state=state);self.assertEqual(rows[0]["current_display"],"3.0.18-alpine");self.assertEqual(rows[0]["available"],"3.0.19-alpine");self.assertTrue(rows[0]["registry"]["update_available"])
 def test_inventory_reports_current_for_equal_registry_version(self):
  state=container_registry.RegistryState(image="haproxy:3.0-alpine",local_digest="sha256:same",remote_digest="sha256:same",tracking_image="haproxy:3.0-alpine",remote_status="ok",current_version="3.0.19-alpine",available_version="3.0.19-alpine",tags_status="ok");rows,_=self._inventory(self._inventory_component(),{"stack":"stack1","id":"haproxy"},"haproxy:3.0-alpine",registry_state=state);self.assertEqual(rows[0]["available"],"current");self.assertEqual(rows[0]["current_display"],"3.0.19-alpine")
 def test_inventory_reports_rate_limit_reason(self):
  state=container_registry.RegistryState(image="haproxy:3.0-alpine",local_digest="sha256:local",remote_digest=None,tracking_image="haproxy:3.0-alpine",remote_status="rate_limited",tags_status="rate_limited");rows,_=self._inventory(self._inventory_component(),{"stack":"stack1","id":"haproxy"},"haproxy:3.0-alpine",registry_state=state);self.assertEqual(rows[0]["available"],"unknown");self.assertEqual(upgrade._human_available(rows[0]),"unknown (rate limited)")
 def test_inventory_reports_unknown_when_registry_comparison_is_incomplete(self):
  state=container_registry.RegistryState(image="haproxy:3.0-alpine",local_digest=None,remote_digest="sha256:remote",tracking_image="haproxy:3.0-alpine",remote_status="ok",tags_status="ok");rows,_=self._inventory(self._inventory_component(),{"stack":"stack1","id":"haproxy"},"haproxy:3.0-alpine",registry_state=state);self.assertEqual(rows[0]["available"],"unknown")
 def test_inventory_offline_does_not_query_registry(self):
  rows,registry=self._inventory(self._inventory_component(),{"stack":"stack1","id":"haproxy"},"haproxy:3.0-alpine",online=False);self.assertEqual(rows[0]["available"],"unchecked");self.assertEqual(rows[0]["current_display"],"3.0-alpine");registry.assert_not_called()
 def test_digest_pin_uses_discovered_human_registry_version(self):
  component=upgrade.Component(stack="stack2",name="firecrawl",service=None,container="firecrawl-api",compose=None,upstream="firecrawl/firecrawl",selectable=False);state=container_registry.RegistryState(image="ghcr.io/firecrawl/firecrawl@sha256:old",local_digest="sha256:old",remote_digest="sha256:new",current_version="2.11.300",available_version="2.11.331",remote_status="ok",tags_status="ok",registry="ghcr.io",repository="firecrawl/firecrawl");rows,registry=self._inventory(component,{"stack":"stack2","id":"firecrawl"},state.image,registry_state=state);self.assertEqual(rows[0]["current_display"],"2.11.300");self.assertEqual(rows[0]["available"],"2.11.331");registry.assert_called_once()
 def test_exact_tag_component_also_uses_its_image_registry(self):
  component=upgrade.Component(stack="stack7",name="open-webui",service=None,container="open-webui",compose=None,upstream="open-webui/open-webui",selectable=True);state=container_registry.RegistryState(image="ghcr.io/open-webui/open-webui:v0.11.3",local_digest="sha256:old",remote_digest="sha256:new",current_version="v0.11.3",available_version="v0.11.4",remote_status="ok",tags_status="ok",registry="ghcr.io",repository="open-webui/open-webui");rows,registry=self._inventory(component,{"stack":"stack7","id":"open-webui"},state.image,registry_state=state);self.assertEqual(rows[0]["available"],"v0.11.4");registry.assert_called_once()
 def test_local_component_is_not_queried_against_registry(self):
  component=upgrade.Component(stack="stack6",name="sandbox",service="hermes-sandbox",container="hermes-sandbox",compose="stack6_-_hermes/docker-compose.yml",upstream=None,selectable=False);rows,registry=self._inventory(component,{"stack":"stack6","id":"sandbox","availability":"local"},"hermes-sandbox:local");self.assertEqual(rows[0]["available"],"local");registry.assert_not_called()
if __name__=="__main__":unittest.main()
