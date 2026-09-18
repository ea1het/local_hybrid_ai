#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Regression tests for operational version authority and guarded upgrade UX."""
from __future__ import annotations
import io,stat,tempfile,unittest
from pathlib import Path
from unittest import mock
from local_ai_cli import upgrade
from local_ai_cli.upgrade import adopt as upgrade_adopt
from local_ai_cli.upgrade import registry as upgrade_registry
from local_ai_cli.upgrade import selection as upgrade_selection
class VersionAuthorityTests(unittest.TestCase):
 def test_selectability_matches_runtime_qualification_state(self):
  records=upgrade.component_records();redis=records["stack2/redis"];self.assertTrue(redis.get("selectable",True));self.assertEqual(redis["execution"],{"mode":"guarded","blocked_by":None});self.assertEqual(redis["apply"]["type"],"env-version")
  for key in ("stack1/haproxy","stack2/rabbitmq","stack5/dockhand"):
   record=records[key];self.assertFalse(record.get("selectable",True),key);self.assertEqual(record["execution"],{"mode":"inventory-only","blocked_by":"executor-not-qualified"});self.assertEqual(record["apply"]["type"],"env-version")
 def test_catalog_no_longer_uses_tracked_compose_pin_as_block_reason(self):
  for key,record in upgrade.component_records().items():self.assertNotEqual(record["execution"].get("blocked_by"),"tracked-compose-pin",key)
 def test_compose_baselines_pin_pre_adoption_runtime_versions(self):
  root=Path(__file__).resolve().parents[2];s1=(root/"stack1_-_haproxy_web"/"docker-compose.yml").read_text();s2=(root/"stack2_-_searxng_firecrawl"/"docker-compose.yml").read_text();s5=(root/"stack5_-_dockhand"/"docker-compose.yml").read_text();self.assertIn("${HAPROXY_VERSION:-3.0.26-alpine3.24}",s1);self.assertIn("${FIRECRAWL_REDIS_VERSION:-8.10.0-alpine3.23}",s2);self.assertIn("${FIRECRAWL_RABBITMQ_VERSION:-3.13.7-alpine}",s2);self.assertIn("${DOCKHAND_REPOSITORY:-fnsys/dockhand}:${DOCKHAND_VERSION:-v1.0.40}",s5);self.assertNotIn("image: haproxy:3.0-alpine",s1);self.assertNotIn("image: redis:alpine",s2);self.assertNotIn("image: rabbitmq:3-alpine",s2)
 def test_human_upgrade_table_calls_runtime_version_installed(self):
  rows=[{"stack":"stack2","component":"redis","actual":"8.10.0-alpine3.23","actual_display":"8.10.0-alpine3.23","available":"8.10.1-alpine3.23","policy":"major-series","selectable":True,"selected":None,"selection_valid":None,"registry":None}];out=io.StringIO()
  with mock.patch("sys.stdout",out):upgrade.print_table(rows)
  header=out.getvalue().splitlines()[0];self.assertIn("INSTALLED",header);self.assertNotIn("ACTUAL",header)
 def test_dockhand_adoption_uses_non_conflicting_split_authority(self):self.assertEqual(upgrade_adopt.AUTHORITIES["stack5/dockhand"],{"type":"split","image_key":"DOCKHAND_REPOSITORY","version_key":"DOCKHAND_VERSION"})
 def test_exact_split_identity_does_not_need_registry_lookup(self):
  c=upgrade.Component("stack7","open-webui","open-webui","open-webui",None,None)
  with mock.patch.object(upgrade_adopt.upgrade_registry,"inspect") as inspect:repository,version=upgrade_adopt._split_identity(c,"ghcr.io/open-webui/open-webui:v0.11.3")
  self.assertEqual((repository,version),("ghcr.io/open-webui/open-webui","v0.11.3"));inspect.assert_not_called()
 def test_tracking_split_identity_resolves_exact_running_version(self):
  c=upgrade.Component("stack2","redis","firecrawl-redis","firecrawl-redis",None,None);state=upgrade_registry.RegistryState(image="redis:alpine",local_digest="sha256:aaa",remote_digest="sha256:bbb",current_version="8.10.0-alpine3.23",available_version="8.10.1-alpine3.23")
  with mock.patch.object(upgrade_adopt.upgrade_registry,"inspect",return_value=state):repository,version=upgrade_adopt._split_identity(c,"redis:alpine")
  self.assertEqual((repository,version),("redis","8.10.0-alpine3.23"))
 def test_selection_baseline_resolves_historical_tracking_runtime(self):
  c=upgrade.Component("stack2","redis","firecrawl-redis","firecrawl-redis","stack2_-_searxng_firecrawl/docker-compose.yml","redis/redis");state=upgrade_registry.RegistryState(image="redis:alpine",local_digest="sha256:aaa",remote_digest="sha256:bbb",current_version="8.10.0-alpine3.23",available_version="8.10.1-alpine3.23")
  with mock.patch.object(upgrade_selection.upgrade,"running_image",return_value="redis:alpine"),mock.patch.object(upgrade_selection.upgrade_registry,"inspect",return_value=state):current=upgrade_selection.current_runtime_version(c,{})
  self.assertEqual(current,"8.10.0-alpine3.23")
 def test_selection_baseline_fails_closed_to_literal_when_registry_resolution_fails(self):
  c=upgrade.Component("stack2","redis","firecrawl-redis","firecrawl-redis","stack2_-_searxng_firecrawl/docker-compose.yml","redis/redis")
  with mock.patch.object(upgrade_selection.upgrade,"running_image",return_value="redis:alpine"),mock.patch.object(upgrade_selection.upgrade_registry,"inspect",side_effect=upgrade_registry.RegistryError("rate limited")):current=upgrade_selection.current_runtime_version(c,{})
  self.assertEqual(current,"alpine")
 def test_adoption_appends_missing_authority_without_rewriting_existing_values(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/".env";path.write_text("SECRET=keep-me\n");path.chmod(0o600);written=upgrade_adopt._apply_missing(path,{"HAPROXY_IMAGE":"haproxy","HAPROXY_VERSION":"3.0.26-alpine3.24"});text=path.read_text();self.assertEqual(written,["HAPROXY_IMAGE","HAPROXY_VERSION"]);self.assertIn("SECRET=keep-me\n",text);self.assertIn("HAPROXY_IMAGE=haproxy\n",text);self.assertIn("HAPROXY_VERSION=3.0.26-alpine3.24\n",text);self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
 def test_adoption_conflict_fails_without_mutating_env(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/".env";original="FIRECRAWL_REDIS_VERSION=8.9.9-alpine\n";path.write_text(original)
   with self.assertRaises(upgrade_adopt.AdoptionError) as ctx:upgrade_adopt._apply_missing(path,{"FIRECRAWL_REDIS_VERSION":"8.10.0-alpine3.23"})
   self.assertEqual(ctx.exception.code,"UPGRADE_ADOPTION_CONFLICT");self.assertEqual(path.read_text(),original)
if __name__=="__main__":unittest.main()
