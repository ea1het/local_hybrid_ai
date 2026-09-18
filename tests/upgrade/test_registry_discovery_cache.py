# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Deterministic tests for bounded persistent registry-discovery caching."""
from __future__ import annotations
import json,tempfile,unittest
from pathlib import Path
from unittest import mock
from local_ai_cli.upgrade import _core_impl as upgrade
from local_ai_cli.upgrade import registry as upgrade_registry
class RegistryDiscoveryCacheTests(unittest.TestCase):
 def component(self):return upgrade.Component(stack="stack7",name="open-webui",service="open-webui",container="open-webui",compose="stack7_-_open-webui/docker-compose.yml",upstream="open-webui/open-webui",selectable=True)
 def state(self,local="sha256:local"):return upgrade_registry.RegistryState(image="ghcr.io/open-webui/open-webui:v0.11.3",local_digest=local,remote_digest="sha256:remote",tracking_image="ghcr.io/open-webui/open-webui:v0.11.3",remote_status="ok",current_version="v0.11.3",available_version="v0.11.4",tags_status="ok",registry="ghcr.io",repository="open-webui/open-webui")
 def test_cached_state_is_reused_inside_ttl(self):
  with tempfile.TemporaryDirectory() as tmp,mock.patch.dict("os.environ",{"LOCAL_AI_RUNTIME_ROOT":tmp,"LOCAL_AI_REGISTRY_CACHE_TTL_SECONDS":"300"},clear=False),mock.patch.object(upgrade.time,"time",return_value=1000.0):
   component=self.component();state=self.state();upgrade._store_registry_state(component,state.image,state)
   with mock.patch.object(upgrade.upgrade_registry,"local_digest",return_value="sha256:local"):cached=upgrade._cached_registry_state(component,state.image)
  self.assertEqual(cached,state)
 def test_cache_misses_when_local_identity_changes(self):
  with tempfile.TemporaryDirectory() as tmp,mock.patch.dict("os.environ",{"LOCAL_AI_RUNTIME_ROOT":tmp},clear=False),mock.patch.object(upgrade.time,"time",return_value=1000.0):
   component=self.component();state=self.state();upgrade._store_registry_state(component,state.image,state)
   with mock.patch.object(upgrade.upgrade_registry,"local_digest",return_value="sha256:different"):cached=upgrade._cached_registry_state(component,state.image)
  self.assertIsNone(cached)
 def test_cache_entry_expires_after_ttl(self):
  with tempfile.TemporaryDirectory() as tmp,mock.patch.dict("os.environ",{"LOCAL_AI_RUNTIME_ROOT":tmp,"LOCAL_AI_REGISTRY_CACHE_TTL_SECONDS":"30"},clear=False):
   component=self.component();state=self.state()
   with mock.patch.object(upgrade.time,"time",return_value=1000.0):upgrade._store_registry_state(component,state.image,state)
   with mock.patch.object(upgrade.time,"time",return_value=1031.0),mock.patch.object(upgrade.upgrade_registry,"local_digest",return_value="sha256:local"):cached=upgrade._cached_registry_state(component,state.image)
  self.assertIsNone(cached)
 def test_cache_file_is_bounded(self):
  with tempfile.TemporaryDirectory() as tmp,mock.patch.dict("os.environ",{"LOCAL_AI_RUNTIME_ROOT":tmp},clear=False):
   entries={f"key-{i}":{"stored_at":float(i),"state":{}} for i in range(upgrade.REGISTRY_CACHE_MAX_ENTRIES+20)};upgrade._save_registry_cache(entries);data=json.loads((Path(tmp)/"platform"/"registry-discovery-cache.json").read_text(encoding="utf-8"))
  self.assertEqual(len(data["entries"]),upgrade.REGISTRY_CACHE_MAX_ENTRIES);self.assertIn(f"key-{upgrade.REGISTRY_CACHE_MAX_ENTRIES+19}",data["entries"]);self.assertNotIn("key-0",data["entries"])
if __name__=="__main__":unittest.main()
