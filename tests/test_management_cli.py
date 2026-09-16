# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Contract tests for the supported ``./local-ai`` management CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from commands import cli, completion

ROOT = Path(__file__).resolve().parents[1]
LOCAL_AI = ROOT / "local-ai"


class ManagementCliContractTests(unittest.TestCase):
    def run_cli(self, *args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        if env_extra:
            env.update(env_extra)
        return subprocess.run([str(LOCAL_AI), *args], cwd=ROOT, text=True, capture_output=True, check=False, env=env)

    def test_root_help_exposes_supported_commands(self):
        cp = self.run_cli()
        self.assertEqual(cp.returncode, 0, cp.stderr)
        for command in ("install", "backup", "restore", "status", "doctor", "inventory", "completion", "start", "stop", "upgrade"):
            self.assertIn(command, cp.stdout)

    def test_start_and_stop_require_numeric_public_stack_ids(self):
        for command in ("start", "stop"):
            with self.subTest(command=command):
                cp = self.run_cli(command, "stack7")
                self.assertEqual(cp.returncode, 2)
                self.assertIn("STACK_SELECTOR_INVALID", cp.stderr)

    def test_upgrade_rejects_internal_stack_selector(self):
        with mock.patch("commands.cli.upgrade_entry.main") as upgrade:
            rc = cli.main(["upgrade", "stack7"])
        self.assertEqual(rc, 2)
        upgrade.assert_not_called()

    def test_upgrade_translates_numeric_selector(self):
        with mock.patch("commands.cli.upgrade_entry.main", return_value=0) as upgrade:
            rc = cli.main(["upgrade", "7"])
        self.assertEqual(rc, 0)
        upgrade.assert_called_once_with(["stack7"], json_output=False)

    def test_upgrade_policy_translates_numeric_selector(self):
        with mock.patch("commands.cli.upgrade_entry.main", return_value=0) as upgrade:
            rc = cli.main(["upgrade", "policy", "7", "open-webui", "set", "minor-series"])
        self.assertEqual(rc, 0)
        upgrade.assert_called_once_with(["policy", "stack7", "open-webui", "set", "minor-series"], json_output=False)

    def test_upgrade_adopt_uses_public_adapter(self):
        with mock.patch("commands.cli.upgrade_adopt.main", return_value=0) as adopt:
            rc = cli.main(["upgrade", "adopt", "7", "--yes"])
        self.assertEqual(rc, 0)
        adopt.assert_called_once_with(["7", "--yes"], json_output=False)

    def test_completion_root_matches_public_commands(self):
        self.assertEqual(
            completion.complete([]),
            ["backup", "completion", "doctor", "install", "inventory", "restore", "start", "status", "stop", "upgrade"],
        )

    def test_completion_start_stop_are_numeric(self):
        self.assertEqual(completion.complete(["start", ""]), [str(i) for i in range(8)])
        self.assertEqual(completion.complete(["stop", ""]), [str(i) for i in range(8)])

    def test_completion_restore_actions_include_backup_listing(self):
        self.assertEqual(completion.complete(["restore", ""]), ["apply", "drill", "list-backup-sets", "plan", "resume"])

    def test_completion_upgrade_stack_selector_is_numeric(self):
        self.assertEqual(completion.complete(["upgrade", ""]), [str(i) for i in range(8)] + ["adopt", "check", "--offline", "policy", "--yes"])

    def test_completion_upgrade_policy_stack_selector_is_numeric(self):
        self.assertEqual(completion.complete(["upgrade", "policy", ""]), [str(i) for i in range(8)])

    def test_completion_upgrade_adopt_stack_selector_is_numeric(self):
        self.assertEqual(completion.complete(["upgrade", "adopt", ""]), [str(i) for i in range(8)])

    def test_completion_command_outputs_shell_integration(self):
        cp = self.run_cli("completion", "bash")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("complete -F _local_ai_complete ./local-ai", cp.stdout)
        self.assertIn("__complete", cp.stdout)

    def test_completion_rejects_unknown_shell(self):
        cp = self.run_cli("completion", "fish")
        self.assertNotEqual(cp.returncode, 0)

    def test_restore_dispatches_public_grammar_to_private_engines(self):
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
            metadata = {
                "schema_version": 1,
                "kind": "local-hybrid-ai-backup-set",
                "created_at": "2026-09-16T12:00:00Z",
                "source_commit": "a" * 40,
                "requested": ["all"],
                "resolved_stacks": [0, 3, 6],
                "artifacts": [],
                "prerequisites": [],
            }
            (backup / "backup.json").write_text(json.dumps(metadata), encoding="utf-8")
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
