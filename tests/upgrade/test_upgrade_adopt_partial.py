#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Regression tests for non-disruptive version-authority adoption on partial installs."""
from __future__ import annotations
import unittest
from types import SimpleNamespace
from unittest import mock
from local_ai_cli import cli
from local_ai_cli.upgrade import adopt as upgrade_adopt
class UpgradeAdoptPartialTests(unittest.TestCase):
 def test_unprepared_missing_component_is_skipped(self):
  component=SimpleNamespace(stack="stack1",name="haproxy",compose="stack1_-_haproxy_web/docker-compose.yml",container="haproxy")
  with mock.patch.dict(upgrade_adopt.AUTHORITIES,{"stack1/haproxy":{"type":"split","image_key":"HAPROXY_IMAGE","version_key":"HAPROXY_VERSION"}},clear=True),mock.patch("local_ai_cli.upgrade.adopt.upgrade.load_catalog",return_value=[component]),mock.patch("local_ai_cli.upgrade.adopt.upgrade.running_image",return_value=None),mock.patch("local_ai_cli.upgrade.adopt._component_prepared",return_value=False):updates,records=upgrade_adopt.desired_updates()
  self.assertEqual(updates,{});self.assertEqual(records,[{"component":"stack1/haproxy","skipped":"stack-not-prepared"}])
 def test_prepared_component_without_runtime_identity_fails_closed(self):
  component=SimpleNamespace(stack="stack1",name="haproxy",compose="stack1_-_haproxy_web/docker-compose.yml",container="haproxy")
  with mock.patch.dict(upgrade_adopt.AUTHORITIES,{"stack1/haproxy":{"type":"split","image_key":"HAPROXY_IMAGE","version_key":"HAPROXY_VERSION"}},clear=True),mock.patch("local_ai_cli.upgrade.adopt.upgrade.load_catalog",return_value=[component]),mock.patch("local_ai_cli.upgrade.adopt.upgrade.running_image",return_value=None),mock.patch("local_ai_cli.upgrade.adopt._component_prepared",return_value=True):
   with self.assertRaises(upgrade_adopt.AdoptionError) as ctx:upgrade_adopt.desired_updates()
  self.assertEqual(ctx.exception.code,"UPGRADE_ADOPTION_RUNTIME_UNAVAILABLE")
 def test_domain_payload_does_not_render_or_serialize(self):
  payload={"schema_version":"1","command":"upgrade.adopt","success":True,"executed":False,"missing_keys":[],"written_keys":[],"components":[]}
  with mock.patch("local_ai_cli.upgrade.adopt.upgrade.ROOT") as root,mock.patch("local_ai_cli.upgrade.adopt.desired_updates",return_value=({},[])),mock.patch("local_ai_cli.upgrade.adopt._read_operational_env",return_value={}):
   root.__truediv__.return_value.is_file.return_value=True;self.assertEqual(upgrade_adopt.json_payload(),payload)
 def test_public_cli_owns_adoption_rendering(self):
  payload={"schema_version":"1","command":"upgrade.adopt","success":True,"executed":False,"missing_keys":[],"written_keys":[],"components":[]}
  with mock.patch("local_ai_cli.cli.upgrade_adopt.json_payload",return_value=payload),mock.patch("local_ai_cli.cli.upgrade_adopt.cli_text",return_value="PLAN"),mock.patch("local_ai_cli.cli.render.render_cli") as renderer:
   self.assertEqual(cli.main(["upgrade","adopt"]),0)
  renderer.assert_called_once_with("PLAN")
if __name__=="__main__":unittest.main()
