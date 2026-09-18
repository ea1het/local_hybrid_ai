# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Contracts for project-managed local components outside registry upgrades."""

from __future__ import annotations

import unittest
from pathlib import Path

from local_ai_cli import upgrade, upgrade_adopt

ROOT = Path(__file__).resolve().parents[2]
RUNNER_DIGEST = "sha256:50c352f0506b1878be93f2e9e97353cd6261cd2e7f7bfe70fcd968d00874f9f9"


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

    def test_gitea_runner_source_identity_is_repo_owned_and_immutable(self):
        compose = (ROOT / "stack4_-_gitea" / "docker-compose.yml").read_text(encoding="utf-8")
        prepare = (ROOT / "stack4_-_gitea" / "01-prepare.sh").read_text(encoding="utf-8")
        env_template = (ROOT / ".env.template").read_text(encoding="utf-8")

        self.assertIn(f"docker.io/gitea/runner:3@{RUNNER_DIGEST}", compose)
        self.assertNotIn("${GITEA_RUNNER_IMAGE", compose)
        required_env_block = prepare.split("for key in ", 1)[1].split("; do", 1)[0]
        self.assertNotIn("GITEA_RUNNER_IMAGE", required_env_block)
        self.assertNotIn("GITEA_RUNNER_IMAGE=", env_template)


if __name__ == "__main__":
    unittest.main()
