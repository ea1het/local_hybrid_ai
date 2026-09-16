# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations
import unittest
from unittest import mock
from commands import status

class StatusOperationalTests(unittest.TestCase):
    def test_runtime_summary_distinguishes_prepared_stopped_and_running(self):
        entry={"required_containers":["x"]}
        self.assertEqual(status._runtime_summary(entry,{"prepared":False,"containers":{}}),("unprepared","-"))
        self.assertEqual(status._runtime_summary(entry,{"prepared":True,"containers":{"x":"exited"}}),("stopped","-"))
        self.assertEqual(status._runtime_summary(entry,{"prepared":True,"containers":{"x":"running/healthy"}}),("running","ready"))
    def test_stack_inventory_aggregates_component_drift_and_runtime(self):
        manifests={5:{"directory":"stack5_-_dockhand"}};lifecycle={"stacks":{"5":{"directory":"stack5_-_dockhand","required_containers":["dockhand"]}}};component_rows=[{"stack":"stack5","component":"dockhand","drift":"no"}]
        with mock.patch("commands.status.install.all_manifests",return_value=manifests),mock.patch("commands.status.install.load_lifecycle",return_value=lifecycle),mock.patch("commands.status.install.validate_registry"),mock.patch("commands.status.install.stack_state",return_value={"prepared":True,"containers":{"dockhand":"running/healthy"}}):rows=status.stack_inventory(component_rows)
        self.assertEqual(rows,[{"stack":"stack5","name":"dockhand","state":"running","health":"ready","drift":"no"}])
    def test_human_status_is_operational_not_version_table(self):
        rows=[{"stack":"stack5","name":"dockhand","state":"running","health":"ready","drift":"no"}]
        text=status.cli_text({"success":True,"stacks":rows,"components":[]});header=text.splitlines()[0]
        self.assertEqual(header.split(),["STACK","NAME","STATE","HEALTH","DRIFT"]);self.assertNotIn("DESIRED",header);self.assertNotIn("ACTUAL",header);self.assertNotIn("DEPLOYED",header)
if __name__=="__main__":unittest.main()
