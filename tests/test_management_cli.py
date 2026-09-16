# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""End-to-end contract tests for the sole supported ``./local-ai`` boundary."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from commands import cli, component_inventory

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "local-ai"


class ManagementCliContractTests(unittest.TestCase):
    def run_cli(self, *args: str, runtime_root: str | None = None, env_extra: dict[str, str] | None = None):
        env = os.environ.copy()
        if runtime_root is not None:
            env["LOCAL_AI_RUNTIME_ROOT"] = runtime_root
        if env_extra:
            env.update(env_extra)
        return subprocess.run([str(CLI), *args], cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)

    def test_install_plan_options_pass_through_public_cli(self):
        cp = self.run_cli("install", "--plan", "7")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("Resolved dependency plan:", cp.stdout)
        self.assertIn("No changes made.", cp.stdout)

    def test_cli_boundary_exposes_versioned_json_upgrade_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("--json", "upgrade", "--offline", runtime_root=tmp)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertEqual(payload["schema_version"], "1")
        self.assertEqual(payload["command"], "upgrade.check")
        self.assertTrue(payload["success"])

    def test_upgrade_contains_all_manifest_declared_upgrade_components(self):
        catalog = component_inventory.compile_upgrade_catalog()
        expected = sum(len(stack["components"]) for stack in catalog["stacks"])
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("--json", "upgrade", "--offline", runtime_root=tmp)
        payload = json.loads(cp.stdout)
        self.assertEqual(len(payload["components"]), expected)
        self.assertTrue(all("selected" in row for row in payload["components"]))
        self.assertTrue(all("actual" in row for row in payload["components"]))
        self.assertTrue(all("policy" in row for row in payload["components"]))
        self.assertTrue(all("selectable" in row for row in payload["components"]))

    def test_inventory_rescan_is_available_through_public_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("--json", "inventory", "rescan", runtime_root=tmp)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertEqual(payload["command"], "inventory.rescan")
        self.assertTrue(payload["success"])
        self.assertTrue(payload["source_fingerprint"].startswith("sha256:"))

    def test_upgrade_check_remains_compatibility_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary = self.run_cli("--json", "upgrade", "--offline", runtime_root=tmp)
            alias = self.run_cli("--json", "upgrade", "check", "--offline", runtime_root=tmp)
        self.assertEqual(primary.returncode, 0, primary.stderr)
        self.assertEqual(alias.returncode, 0, alias.stderr)
        self.assertEqual(json.loads(primary.stdout)["components"], json.loads(alias.stdout)["components"])

    def test_human_upgrade_table_uses_installed_and_numeric_stack_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("upgrade", "--offline", runtime_root=tmp)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        header = cp.stdout.splitlines()[0]
        self.assertIn("INSTALLED", header)
        self.assertNotIn("ACTUAL", header)
        self.assertNotIn("CURRENT", header)
        data_lines = [line for line in cp.stdout.splitlines() if line and not line.startswith("STACK") and not line.startswith("-")]
        self.assertTrue(any(line.startswith("7 ") and "open-webui" in line for line in data_lines))
        self.assertFalse(any(line.startswith("stack") for line in data_lines))

    def test_json_upgrade_contract_keeps_stable_stack_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("--json", "upgrade", "--offline", runtime_root=tmp)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        payload = json.loads(cp.stdout)
        open_webui = next(row for row in payload["components"] if row["component"] == "open-webui")
        self.assertEqual(open_webui["stack"], "stack7")
        self.assertIn("actual", open_webui)

    def test_single_component_stack_policy_shorthand_persists_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("upgrade", "policy", "7", "set", "major-series", runtime_root=tmp)
            self.assertEqual(cp.returncode, 0, cp.stderr)
            policy = json.loads((Path(tmp) / "platform" / "upgrade-policy.json").read_text())
        self.assertEqual(policy["overrides"]["stack7/open-webui"], "major-series")

    def test_public_upgrade_rejects_internal_stack_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("upgrade", "stack7", "open-webui", "clear", runtime_root=tmp)
        self.assertEqual(cp.returncode, 2)
        self.assertIn("STACK_SELECTOR_INVALID", cp.stderr)

    def test_multicomponent_stack_requires_component_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("upgrade", "3", "select", "1.100.0", runtime_root=tmp)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("multiple components", cp.stderr)

    def test_nonselectable_component_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("upgrade", "3", "postgresql", "select", "17.11-alpine3.24", runtime_root=tmp)
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
            plan_path.write_text(json.dumps({"schema_version": 1, "selected": {"stack7/open-webui": {"stack": "stack7", "component": "open-webui", "current_at_selection": "definitely-not-current", "version": "v0.11.4", "policy_at_selection": "minor-series"}}}), encoding="utf-8")
            cp = self.run_cli("upgrade", "--yes", runtime_root=tmp)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("UPGRADE_PLAN_STALE", cp.stderr)

    def test_json_errors_have_stable_error_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("--json", "upgrade", "--yes", runtime_root=tmp)
        self.assertNotEqual(cp.returncode, 0)
        payload = json.loads(cp.stdout)
        self.assertEqual(payload["error"]["code"], "UPGRADE_NOTHING_SELECTED")

    def test_restore_actions_translate_public_grammar_to_private_implementations(self):
        cases = {
            "plan": (["plan", "/backup/set"], "restore-all.py", ["/backup/set", "--dry-run"]),
            "drill": (["drill", "/backup/set", "--destination", "/tmp/drill"], "restore-drill.py", ["/backup/set", "--destination", "/tmp/drill"]),
            "apply": (["apply", "/backup/set", "--check-clean-target"], "restore-live.py", ["/backup/set", "--check-clean-target"]),
            "resume": (["resume", "/backup/set", "--memory-sync-ssh-bootstrap", "/ssh"], "restore-resume.py", ["/backup/set", "--memory-sync-ssh-bootstrap", "/ssh"]),
        }
        for action, (public_args, filename, internal_args) in cases.items():
            with self.subTest(action=action), mock.patch.object(cli, "_run_internal", return_value=0) as run:
                rc = cli.restore_command(public_args, json_output=False)
                self.assertEqual(rc, 0)
                path, args = run.call_args.args
                self.assertEqual(path, ROOT / "commands" / "recovery" / filename)
                self.assertEqual(args, internal_args)

    def test_restore_help_is_owned_by_local_ai_and_hides_private_scripts(self):
        for action in ("plan", "drill", "apply", "resume", "list-backup-sets"):
            with self.subTest(action=action):
                cp = self.run_cli("restore", action, "--help")
                self.assertEqual(cp.returncode, 0, cp.stderr)
                self.assertIn(f"usage: local-ai restore {action}", cp.stdout.lower())
                for private in ("restore-all.py", "restore-drill.py", "restore-live.py", "restore-resume.py"):
                    self.assertNotIn(private, cp.stdout + cp.stderr)

    def test_restore_without_action_shows_public_restore_help(self):
        cp = self.run_cli("restore")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("list-backup-sets", cp.stdout)
        self.assertIn("plan", cp.stdout)
        self.assertIn("drill", cp.stdout)
        self.assertIn("apply", cp.stdout)
        self.assertIn("resume", cp.stdout)
        self.assertNotIn("restore-all.py", cp.stdout + cp.stderr)

    def test_list_backup_sets_discovers_completed_recovery_points(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup = root / "backup-20260916T120000Z"
            backup.mkdir()
            (backup / "checksums.sha256").write_text("x\n", encoding="utf-8")
            (backup / "backup.json").write_text(json.dumps({"kind": "local-hybrid-ai-backup-set", "completed": True, "created_at": "2026-09-16T12:00:00Z", "source_commit": "a" * 40, "resolved_stacks": [0, 3, 6]}), encoding="utf-8")
            cp = self.run_cli("restore", "list-backup-sets", env_extra={"DR_BACKUP_ROOT": tmp})
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("backup-20260916T120000Z", cp.stdout)
        self.assertIn("COMPLETED", cp.stdout)
        self.assertIn("0,3,6", cp.stdout)

    def test_json_list_backup_sets_has_public_versioned_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("--json", "restore", "list-backup-sets", env_extra={"DR_BACKUP_ROOT": tmp})
        self.assertEqual(cp.returncode, 0, cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertEqual(payload["command"], "restore.list-backup-sets")
        self.assertTrue(payload["success"])
        self.assertEqual(payload["backup_sets"], [])

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
