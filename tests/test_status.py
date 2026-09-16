# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""State-model and operational-status regression tests."""
from __future__ import annotations
import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from commands import component_state,status,upgrade_registry
class ComponentStateTests(unittest.TestCase):
 def test_deployed_version_comes_from_latest_success_only(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);platform=root/"platform";platform.mkdir(parents=True);events=[{"success":True,"upgraded":[{"stack":"stack6","component":"hermes","version":"v1"}]},{"success":False,"selected":[{"stack":"stack6","component":"hermes","version":"v2"}]},{"success":True,"upgraded":[{"stack":"stack6","component":"hermes","version":"v3"}]}];(platform/"upgrade-history.jsonl").write_text("".join(json.dumps(e)+"\n" for e in events),encoding="utf-8");deployed=component_state.deployed_versions(root)
  self.assertEqual(deployed["stack6/hermes"],"v3")
 def test_drift_is_yes_no_or_na(self):
  self.assertEqual(component_state.drift("v1","v1"),"no");self.assertEqual(component_state.drift("v1","v2"),"yes");self.assertEqual(component_state.drift("v1","n/a"),"yes");self.assertEqual(component_state.drift("n/a","n/a"),"n/a")
 def test_floating_reference_detection(self):
  self.assertTrue(component_state.is_floating_image_reference("redis:alpine"));self.assertTrue(component_state.is_floating_image_reference("rabbitmq:3-alpine"));self.assertTrue(component_state.is_floating_image_reference("haproxy:3.0-alpine"));self.assertFalse(component_state.is_floating_image_reference("ghcr.io/open-webui/open-webui:v0.11.3"));self.assertFalse(component_state.is_floating_image_reference("postgres:17.10-alpine@sha256:abcd"))
 def test_exact_desired_resolves_legacy_floating_runtime_without_advancing_intent(self):
  component=SimpleNamespace(container="firecrawl-redis");state=SimpleNamespace(current_version="8.10.0-alpine3.23",available_version="8.10.1-alpine3.23",local_digest="sha256:old",remote_digest="sha256:new")
  with mock.patch("commands.component_state.upgrade_registry.inspect",return_value=state) as inspect_mock:desired,actual,drift=component_state.resolve_identity(component,"redis:8.10.0-alpine3.23","redis:alpine")
  inspect_mock.assert_called_once_with("firecrawl-redis","redis:alpine");self.assertEqual((desired,actual,drift),("8.10.0-alpine3.23","8.10.0-alpine3.23","no"))
 def test_floating_desired_uses_registry_identity_but_failure_is_fail_closed(self):
  component=SimpleNamespace(container="firecrawl-redis");state=SimpleNamespace(current_version="8.10.0-alpine3.23",available_version="8.10.1-alpine3.23",local_digest="sha256:old",remote_digest="sha256:new")
  with mock.patch("commands.component_state.upgrade_registry.inspect",return_value=state):desired,actual,drift=component_state.resolve_identity(component,"redis:alpine","redis:alpine")
  self.assertEqual((desired,actual,drift),("8.10.1-alpine3.23","8.10.0-alpine3.23","yes"))
  with mock.patch("commands.component_state.upgrade_registry.inspect",side_effect=upgrade_registry.RegistryError("rate limited")):desired,actual,drift=component_state.resolve_identity(component,"redis:alpine","redis:alpine")
  self.assertEqual((desired,actual,drift),("alpine","alpine","n/a"))
 def test_aggregate_drift_prefers_yes_then_no_then_na(self):
  self.assertEqual(component_state.aggregate_drift([{"drift":"n/a"},{"drift":"yes"}]),"yes");self.assertEqual(component_state.aggregate_drift([{"drift":"n/a"},{"drift":"no"}]),"no");self.assertEqual(component_state.aggregate_drift([{"drift":"n/a"}]),"n/a")
class StatusOperationalTests(unittest.TestCase):
 def test_local_components_do_not_use_registry_version_drift(self):
  component=SimpleNamespace(stack="stack4",name="runner",container="gitea-runner");record={"stack":"stack4","id":"runner","availability":"local","selectable":False,"default_policy":"manual","execution":{"mode":"inventory-only","blocked_by":"local-managed"}}
  with mock.patch("commands.status.upgrade.read_env",return_value={}),mock.patch("commands.status.upgrade.load_catalog",return_value=[component]),mock.patch("commands.status.upgrade.component_records",return_value={"stack4/runner":record}),mock.patch("commands.status.upgrade.running_image",return_value="docker.io/gitea/runner:3"),mock.patch("commands.status.component_state.resolve_identity") as resolve:rows=status.inventory(deployed_versions={})
  resolve.assert_not_called();self.assertEqual(rows,[{"stack":"stack4","component":"runner","desired":"local","deployed":"local","actual":"local","drift":"n/a"}])
 def test_runtime_summary_distinguishes_running_stopped_partial_and_unprepared(self):
  entry={"required_containers":["a","b"]};self.assertEqual(status._runtime_summary(entry,{"prepared":True,"containers":{"a":"running","b":"running/healthy"}}),("running","ready"));self.assertEqual(status._runtime_summary(entry,{"prepared":True,"containers":{"a":"exited","b":"absent"}}),("stopped","-"));self.assertEqual(status._runtime_summary(entry,{"prepared":True,"containers":{"a":"running","b":"exited"}}),("partial","degraded"));self.assertEqual(status._runtime_summary(entry,{"prepared":False,"containers":{}}),("unprepared","-"))
 def test_stack_inventory_aggregates_component_drift_and_runtime(self):
  manifests={5:{"directory":"stack5_-_dockhand"}};lifecycle={"stacks":{"5":{"directory":"stack5_-_dockhand","required_containers":["dockhand"]}}};component_rows=[{"stack":"stack5","component":"dockhand","drift":"no"}]
  with mock.patch("commands.status.install.all_manifests",return_value=manifests),mock.patch("commands.status.install.load_lifecycle",return_value=lifecycle),mock.patch("commands.status.install.validate_registry"),mock.patch("commands.status.install.stack_state",return_value={"prepared":True,"containers":{"dockhand":"running/healthy"}}):rows=status.stack_inventory(component_rows)
  self.assertEqual(rows,[{"stack":"stack5","name":"dockhand","state":"running","health":"ready","drift":"no"}])
 def test_human_status_is_operational_not_version_table(self):
  rows=[{"stack":"stack5","name":"dockhand","state":"running","health":"ready","drift":"no"}];text=status.cli_text({"success":True,"stacks":rows,"components":[]});header=text.splitlines()[0];self.assertEqual(header.split(),["STACK","NAME","STATE","HEALTH","DRIFT"]);self.assertNotIn("DESIRED",header);self.assertNotIn("ACTUAL",header);self.assertNotIn("DEPLOYED",header)
if __name__=="__main__":unittest.main()
