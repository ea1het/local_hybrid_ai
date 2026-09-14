# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Regression tests for non-disruptive version-authority adoption on partial installs."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from commands import upgrade_adopt


class UpgradeAdoptPartialTests(unittest.TestCase):
    def test_unprepared_missing_component_is_skipped(self):
        component = SimpleNamespace(
            stack="stack1",
            name="haproxy",
            compose="stack1_-_haproxy_web/docker-compose.yml",
            container="haproxy",
        )
        with mock.patch.dict(
            upgrade_adopt.AUTHORITIES,
            {"stack1/haproxy": {"type": "split", "image_key": "HAPROXY_IMAGE", "version_key": "HAPROXY_VERSION"}},
            clear=True,
        ), mock.patch("commands.upgrade_adopt.upgrade.load_catalog", return_value=[component]), \
             mock.patch("commands.upgrade_adopt.upgrade.running_image", return_value=None), \
             mock.patch("commands.upgrade_adopt._component_prepared", return_value=False):
            updates, records = upgrade_adopt.desired_updates()
        self.assertEqual(updates, {})
        self.assertEqual(records, [{"component": "stack1/haproxy", "skipped": "stack-not-prepared"}])

    def test_prepared_component_without_runtime_identity_fails_closed(self):
        component = SimpleNamespace(
            stack="stack1",
            name="haproxy",
            compose="stack1_-_haproxy_web/docker-compose.yml",
            container="haproxy",
        )
        with mock.patch.dict(
            upgrade_adopt.AUTHORITIES,
            {"stack1/haproxy": {"type": "split", "image_key": "HAPROXY_IMAGE", "version_key": "HAPROXY_VERSION"}},
            clear=True,
        ), mock.patch("commands.upgrade_adopt.upgrade.load_catalog", return_value=[component]), \
             mock.patch("commands.upgrade_adopt.upgrade.running_image", return_value=None), \
             mock.patch("commands.upgrade_adopt._component_prepared", return_value=True):
            with self.assertRaises(upgrade_adopt.AdoptionError) as ctx:
                upgrade_adopt.desired_updates()
        self.assertEqual(ctx.exception.code, "UPGRADE_ADOPTION_RUNTIME_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
