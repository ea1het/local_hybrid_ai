#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Contract tests for explicit upgrade execution safety metadata.

The catalog must explain why inventory-only components cannot be selected, while
selectable components must declare guarded execution. LiteLLM remains blocked
until its migration/compatibility policy is made explicit.
"""

from __future__ import annotations

import unittest
from unittest import mock

from local_ai_cli import upgrade


class UpgradeExecutionMetadataTests(unittest.TestCase):
    def test_catalog_declares_execution_contract_for_every_component(self):
        records = upgrade.component_records()
        self.assertTrue(records)
        for key, record in records.items():
            execution = record["execution"]
            if record.get("selectable", True):
                self.assertEqual(execution, {"mode": "guarded", "blocked_by": None}, key)
            else:
                self.assertIn(execution["mode"], {"inventory-only", "not-applicable"}, key)
                self.assertIsInstance(execution["blocked_by"], str, key)
                self.assertTrue(execution["blocked_by"], key)

    def test_litellm_remains_non_selectable_until_migration_policy_exists(self):
        record = upgrade.component_records()["stack3/litellm"]
        self.assertFalse(record["selectable"])
        self.assertEqual(record["execution"]["mode"], "inventory-only")
        self.assertEqual(record["execution"]["blocked_by"], "migration-policy-required")

    def test_inventory_exposes_execution_metadata(self):
        component = upgrade.Component(
            stack="stack0",
            name="platform-foundation",
            service=None,
            container=None,
            compose=None,
            upstream=None,
            selectable=False,
        )
        record = {
            "id": "platform-foundation",
            "stack": "stack0",
            "availability": "n/a",
            "default_policy": "manual",
            "selectable": False,
            "execution": {"mode": "not-applicable", "blocked_by": "non-versioned-component"},
        }
        policy_state = {"effective_policy": "manual", "selection_valid": None}
        with mock.patch("local_ai_cli.upgrade.load_catalog", return_value=[component]), \
             mock.patch("local_ai_cli.upgrade.component_records", return_value={"stack0/platform-foundation": record}), \
             mock.patch("local_ai_cli.upgrade.read_env", return_value={}), \
             mock.patch("local_ai_cli.upgrade.load_plan", return_value={"schema_version": 1, "selected": {}}), \
             mock.patch("local_ai_cli.upgrade.upgrade_policy.selection_status", return_value=policy_state):
            rows = upgrade.inventory(query_upstream=False)
        self.assertEqual(rows[0]["execution"], record["execution"])


if __name__ == "__main__":
    unittest.main()
