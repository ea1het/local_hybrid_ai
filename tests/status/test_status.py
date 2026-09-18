# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Operational-status regression tests owned by the status package."""
from __future__ import annotations
import unittest
from unittest import mock
from local_ai_cli import status
class StatusOperationalTests(unittest.TestCase):
 def test_runtime_summary_distinguishes_running_stopped_partial_and_unprepared(self):
  entry={"required_containers":["a","b"]};self.assertEqual(status._runtime_summary(entry,{"prepared":True,"containers":{"a":"running","b":"running/healthy"}}),("running","ready"));self.assertEqual(status._runtime_summary(entry,{"prepared":True,"containers":{"a":"exited","b":"absent"}}),("stopped","-"));self.assertEqual(status._runtime_summary(entry,{"prepared":True,"containers":{"a":"running","b":"exited"}}),("partial","degraded"));self.assertEqual(status._runtime_summary(entry,{"prepared":False,"containers":{}}),("unprepared","-"))
 def test_stack_inventory_contains_only_operational_state(self):
  manifests={5:{"directory":"stack5_-_dockhand"}};lifecycle={"stacks":{"5":{"directory":"stack5_-_dockhand","required_containers":["dockhand"]}}}
  with mock.patch("local_ai_cli.status.api.install.all_manifests",return_value=manifests),mock.patch("local_ai_cli.status.api.install.load_lifecycle",return_value=lifecycle),mock.patch("local_ai_cli.status.api.install.validate_registry"),mock.patch("local_ai_cli.status.api.install.stack_state",return_value={"prepared":True,"containers":{"dockhand":"running/healthy"}}):rows=status.stack_inventory()
  self.assertEqual(rows,[{"stack":"stack5","name":"dockhand","state":"running","health":"ready"}])
 def test_json_status_contains_no_upgrade_state(self):
  stacks=[{"stack":"stack5","name":"dockhand","state":"running","health":"ready"}]
  with mock.patch("local_ai_cli.status.api.stack_inventory",return_value=stacks):payload=status.json_payload()
  self.assertEqual(payload,{"schema_version":"4","command":"status","success":True,"stacks":stacks})
  serialized=str(payload).lower()
  for forbidden in ("desired","deployed","actual","drift","available","selected","policy"):self.assertNotIn(forbidden,serialized)
 def test_human_status_contains_only_operational_columns(self):
  rows=[{"stack":"stack5","name":"dockhand","state":"running","health":"ready"}];text=status.cli_text({"success":True,"stacks":rows});self.assertEqual(text.splitlines()[0].split(),["STACK","NAME","STATE","HEALTH"])
 def test_status_does_not_depend_on_upgrade(self):
  source=open(status.api.__file__,encoding="utf-8").read();self.assertNotIn("local_ai_cli.upgrade",source);self.assertNotIn("upgrade_registry",source);self.assertNotIn("from local_ai_cli import upgrade",source)
if __name__=="__main__":unittest.main()
