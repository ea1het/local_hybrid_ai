#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Public upgrade contracts for automation, identity and fail-closed mutation."""

from __future__ import annotations
import json, os, subprocess, tempfile, unittest
from pathlib import Path
from local_ai_cli.common import component_inventory

ROOT = Path(__file__).resolve().parents[2]


class UpgradePublicContractTests(unittest.TestCase):
    def run_cli(self, *args, runtime_root=None):
        env = os.environ.copy()
        if runtime_root is not None:
            env["LOCAL_AI_RUNTIME_ROOT"] = runtime_root
        return subprocess.run(
            [str(ROOT / "local-ai"), *args],
            cwd=ROOT,
            env=env,
            text=True,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
        )

    def test_cli_boundary_exposes_versioned_json_upgrade_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("--json", "upgrade", "--offline", runtime_root=tmp)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertEqual(payload["schema_version"], "1")
        self.assertEqual(payload["command"], "upgrade.check")
        self.assertTrue(payload["success"])

    def test_upgrade_contains_all_manifest_declared_components(self):
        expected = sum(len(stack["components"]) for stack in component_inventory.compile_upgrade_catalog()["stacks"])
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("upgrade", "--offline", "--json", runtime_root=tmp)
        payload = json.loads(cp.stdout)
        self.assertEqual(len(payload["components"]), expected)
        for key in ("selected", "actual", "policy", "selectable"):
            self.assertTrue(all(key in row for row in payload["components"]))

    def test_upgrade_check_remains_compatibility_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary = self.run_cli("--json", "upgrade", "--offline", runtime_root=tmp)
            alias = self.run_cli("upgrade", "check", "--offline", "--json", runtime_root=tmp)
        self.assertEqual(primary.returncode, 0, primary.stderr)
        self.assertEqual(alias.returncode, 0, alias.stderr)
        self.assertEqual(json.loads(primary.stdout)["components"], json.loads(alias.stdout)["components"])

    def test_read_only_upgrade_accepts_yes_as_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("upgrade", "check", "--offline", "--yes", "--json", runtime_root=tmp)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertEqual(json.loads(cp.stdout)["command"], "upgrade.check")

    def test_json_upgrade_keeps_stable_stack_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("upgrade", "--offline", "--json", runtime_root=tmp)
        row = next(r for r in json.loads(cp.stdout)["components"] if r["component"] == "open-webui")
        self.assertEqual(row["stack"], "stack7")
        self.assertIn("actual", row)

    def test_policy_mutation_requires_yes_noninteractive(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("upgrade", "policy", "7", "set", "major-series", "--json", runtime_root=tmp)
            self.assertEqual(cp.returncode, 2)
            payload = json.loads(cp.stdout)
            self.assertEqual(payload["error"]["code"], "CONFIRMATION_REQUIRED")
            self.assertFalse((Path(tmp) / "platform" / "upgrade-policy.json").exists())

    def test_policy_shorthand_persists_override_with_yes(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("upgrade", "policy", "7", "set", "major-series", "--yes", runtime_root=tmp)
            self.assertEqual(cp.returncode, 0, cp.stderr)
            policy = json.loads((Path(tmp) / "platform" / "upgrade-policy.json").read_text())
        self.assertEqual(policy["overrides"]["stack7/open-webui"], "major-series")

    def test_public_upgrade_rejects_internal_stack_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("upgrade", "stack7", "open-webui", "clear", "--yes", runtime_root=tmp)
        self.assertEqual(cp.returncode, 2)
        self.assertIn("STACK_SELECTOR_INVALID", cp.stderr)

    def test_multicomponent_stack_requires_component_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("upgrade", "3", "select", "1.100.0", "--yes", runtime_root=tmp)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("multiple components", cp.stderr)

    def test_nonselectable_component_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("upgrade", "4", "runner", "select", "4", "--yes", runtime_root=tmp)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("UPGRADE_COMPONENT_NOT_SELECTABLE", cp.stderr)

    def test_upgrade_yes_never_auto_selects_available_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("upgrade", "--yes", runtime_root=tmp)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("UPGRADE_NOTHING_SELECTED", cp.stderr)

    def test_stale_plan_fails_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "platform" / "upgrade-plan.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "selected": {
                            "stack7/open-webui": {
                                "stack": "stack7",
                                "component": "open-webui",
                                "current_at_selection": "definitely-not-current",
                                "version": "v0.11.4",
                                "policy_at_selection": "minor-series",
                            }
                        },
                    }
                )
            )
            cp = self.run_cli("upgrade", "--yes", runtime_root=tmp)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("UPGRADE_PLAN_STALE", cp.stderr)

    def test_json_errors_have_stable_error_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("upgrade", "--yes", "--json", runtime_root=tmp)
        self.assertNotEqual(cp.returncode, 0)
        self.assertEqual(json.loads(cp.stdout)["error"]["code"], "UPGRADE_NOTHING_SELECTED")


if __name__ == "__main__":
    unittest.main()
