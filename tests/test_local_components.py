# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Contracts for project-managed local components outside registry upgrades."""

from __future__ import annotations

import unittest

from commands import upgrade, upgrade_adopt


class LocalComponentTests(unittest.TestCase):
    def test_gitea_runner_and_hermes_sandbox_are_local_inventory_components(self):
        records = upgrade.component_records()

        runner = records["stack4/runner"]
        self.assertEqual(runner["availability"], "local")
        self.assertFalse(runner["selectable"])
        self.assertEqual(runner["execution"], {"mode": "inventory-only", "blocked_by": "local-managed"})
        self.assertNotIn("upstream", runner)
        self.assertNotIn("apply", runner)

        sandbox = records["stack6/sandbox"]
        self.assertEqual(sandbox["availability"], "local")
        self.assertFalse(sandbox["selectable"])
        self.assertNotIn("upstream", sandbox)
        self.assertNotIn("apply", sandbox)

    def test_local_components_are_not_operational_version_authorities(self):
        self.assertNotIn("stack4/runner", upgrade_adopt.AUTHORITIES)
        self.assertNotIn("stack6/sandbox", upgrade_adopt.AUTHORITIES)


if __name__ == "__main__":
    unittest.main()
