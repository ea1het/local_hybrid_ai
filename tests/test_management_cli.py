# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""End-to-end contract tests for the sole supported ``./local-ai`` boundary.

These tests invoke or dispatch through the public CLI to protect option
passthrough, stable JSON schemas/error codes, numeric human stack display,
stable machine stack identity, explicit upgrade selection, policy shorthand,
selectability gates and recovery-subpackage routing. They intentionally avoid
making private implementation paths part of the operator contract.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from commands import cli

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "local-ai"


class ManagementCliContractTests(unittest.TestCase):
    def run_cli(self, *args: str, runtime_root: str | None = None):
        env = os.environ.copy()
        if runtime_root is not None:
            env["LOCAL_AI_RUNTIME_ROOT"] = runtime_root
        return subprocess.run(
            [str(CLI), *args], cwd=ROOT, env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )

    def test_install_plan_options_pass_through_public_cli(self):
        cp = self.run_cli("install", "--plan", "7")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("Resolved dependency plan:", cp.stdout)
        self.assertIn("No changes made.", cp.stdout)

    def test_cli_boundary_exposes_versioned_json_upgrade_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("--json", "upgrade", "check", "--offline", runtime_root=tmp)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertEqual(payload["schema_version"], "1")
        self.assertEqual(payload["command"], "upgrade.check")
        self.assertTrue(payload["success"])

    def test_upgrade_check_contains_all_declared_components_and_selected_column(self):
        catalog = json.loads((ROOT / "commands" / "upgrade-components.json").read_text())
        expected = sum(len(stack["components"]) for stack in catalog["stacks"])
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("--json", "upgrade", "check", "--offline", runtime_root=tmp)
        payload = json.loads(cp.stdout)
        self.assertEqual(len(payload["components"]), expected)
        self.assertTrue(all("selected" in row for row in payload["components"]))
        self.assertTrue(all("actual" in row for row in payload["components"]))
        self.assertTrue(all("policy" in row for row in payload["components"]))
        self.assertTrue(all("selectable" in row for row in payload["components"]))

    def test_human_upgrade_table_uses_numeric_stack_column_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("upgrade", "check", "--offline", runtime_root=tmp)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("ACTUAL", cp.stdout.splitlines()[0])
        self.assertNotIn("CURRENT", cp.stdout.splitlines()[0])
        data_lines = [line for line in cp.stdout.splitlines() if line and not line.startswith("STACK") and not line.startswith("-")]
        self.assertTrue(any(line.startswith("7 ") and "open-webui" in line for line in data_lines))
        self.assertFalse(any(line.startswith("stack") for line in data_lines))

    def test_json_upgrade_contract_keeps_stable_stack_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("--json", "upgrade", "check", "--offline", runtime_root=tmp)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        payload = json.loads(cp.stdout)
        open_webui = next(row for row in payload["components"] if row["component"] == "open-webui")
        self.assertEqual(open_webui["stack"], "stack7")

    def test_single_component_stack_policy_shorthand_persists_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli(
                "upgrade", "policy", "stack7", "set", "major-series",
                runtime_root=tmp,
            )
            self.assertEqual(cp.returncode, 0, cp.stderr)
            policy = json.loads((Path(tmp) / "platform" / "upgrade-policy.json").read_text())
        self.assertEqual(policy["overrides"]["stack7/open-webui"], "major-series")

    def test_multicomponent_stack_requires_component_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("upgrade", "stack3", "select", "1.100.0", runtime_root=tmp)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("multiple components", cp.stderr)

    def test_nonselectable_component_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("upgrade", "stack1", "select", "3.1-alpine", runtime_root=tmp)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("UPGRADE_COMPONENT_NOT_SELECTABLE", cp.stderr)

    def test_upgrade_yes_never_auto_selects_available_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("upgrade", "--yes", runtime_root=tmp)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("no upgrades are selected", cp.stderr)
        self.assertIn("UPGRADE_NOTHING_SELECTED", cp.stderr)

    def test_stale_plan_fails_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "platform" / "upgrade-plan.json"
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text(json.dumps({
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
            }), encoding="utf-8")
            cp = self.run_cli("upgrade", "--yes", runtime_root=tmp)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("UPGRADE_PLAN_STALE", cp.stderr)

    def test_json_errors_have_stable_error_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("--json", "upgrade", "--yes", runtime_root=tmp)
        self.assertNotEqual(cp.returncode, 0)
        payload = json.loads(cp.stdout)
        self.assertEqual(payload["error"]["code"], "UPGRADE_NOTHING_SELECTED")

    def test_restore_actions_dispatch_only_to_recovery_subpackage(self):
        expected = {
            "plan": "restore-all.py",
            "drill": "restore-drill.py",
            "apply": "restore-live.py",
            "resume": "restore-resume.py",
        }
        for action, filename in expected.items():
            with self.subTest(action=action), mock.patch.object(cli, "_run_internal", return_value=0) as run:
                rc = cli.restore_command([action, "arg"], json_output=False)
                self.assertEqual(rc, 0)
                path, args = run.call_args.args
                self.assertEqual(path, ROOT / "commands" / "recovery" / filename)
                self.assertEqual(args, ["arg"])

    def test_backup_dispatch_uses_recovery_subpackage(self):
        with mock.patch.object(cli, "_run_internal", return_value=0) as run:
            rc = cli.main(["backup"])
        self.assertEqual(rc, 0)
        path, args = run.call_args.args
        self.assertEqual(path, ROOT / "commands" / "recovery" / "backup-all.py")
        self.assertEqual(args, [])

    def test_backup_destination_option_passes_through_public_cli(self):
        with mock.patch.object(cli, "_run_internal", return_value=0) as run:
            rc = cli.main(["backup", "--destination", "/mnt/backup/local-ai"])
        self.assertEqual(rc, 0)
        path, args = run.call_args.args
        self.assertEqual(path, ROOT / "commands" / "recovery" / "backup-all.py")
        self.assertEqual(args, ["--destination", "/mnt/backup/local-ai"])

    def test_json_backup_preserves_destination_and_adds_json_flag(self):
        with mock.patch.object(cli, "_run_internal", return_value=0) as run:
            rc = cli.main(["--json", "backup", "--destination", "/mnt/backup/local-ai"])
        self.assertEqual(rc, 0)
        path, args = run.call_args.args
        self.assertEqual(path, ROOT / "commands" / "recovery" / "backup-all.py")
        self.assertEqual(args, ["--destination", "/mnt/backup/local-ai", "--json"])


if __name__ == "__main__":
    unittest.main()
