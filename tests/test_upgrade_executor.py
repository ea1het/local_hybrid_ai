# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Safety tests for recovery-first targeted upgrade execution.

These tests protect atomic `.env` mutation, installation-owned target image
construction, read-only target preflight, immutable digest revalidation,
recovery-point JSON consumption, empty-selection rejection and policy
revalidation before any mutation occurs.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from commands import upgrade_executor, upgrade_registry


class UpgradeExecutorSafetyTests(unittest.TestCase):
    def test_atomic_env_update_changes_only_explicit_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("A=1\nOPENWEBUI_VERSION=v0.11.3\nB=2\n", encoding="utf-8")
            upgrade_executor._atomic_update_env(path, {"OPENWEBUI_VERSION": "v0.12.0"})
            self.assertEqual(
                path.read_text(encoding="utf-8"),
                "A=1\nOPENWEBUI_VERSION=v0.12.0\nB=2\n",
            )

    def test_atomic_env_update_fails_if_key_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("A=1\n", encoding="utf-8")
            with self.assertRaises(upgrade_executor.UpgradeExecutionError) as ctx:
                upgrade_executor._atomic_update_env(path, {"OPENWEBUI_VERSION": "v0.12.0"})
            self.assertEqual(ctx.exception.code, "UPGRADE_ENV_KEY_MISSING")
            self.assertEqual(path.read_text(encoding="utf-8"), "A=1\n")

    def test_target_image_ref_uses_installation_owned_repository_and_selected_version(self):
        component = {"apply": {"image_env_key": "HERMES_IMAGE"}}
        selection = {"version": "v2026.9.11"}
        env = {"HERMES_IMAGE": "nousresearch/hermes-agent"}
        self.assertEqual(
            upgrade_executor._target_image_ref("stack6/hermes", component, selection, env),
            "nousresearch/hermes-agent:v2026.9.11",
        )

    @mock.patch("commands.upgrade_executor.subprocess.run")
    def test_target_image_preflight_is_read_only_manifest_inspection(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        with tempfile.TemporaryDirectory() as tmp:
            upgrade_executor._preflight_target_image(
                Path(tmp),
                "nousresearch/hermes-agent:v2026.9.11",
            )
        run.assert_called_once()
        args, kwargs = run.call_args
        self.assertEqual(
            args[0],
            ["docker", "manifest", "inspect", "nousresearch/hermes-agent:v2026.9.11"],
        )
        self.assertFalse(kwargs["check"])

    @mock.patch("commands.upgrade_executor.subprocess.run")
    def test_target_image_preflight_rejects_missing_image(self, run):
        run.return_value = subprocess.CompletedProcess([], 1, "", "manifest unknown")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(upgrade_executor.UpgradeExecutionError) as ctx:
                upgrade_executor._preflight_target_image(
                    Path(tmp),
                    "nousresearch/hermes-agent:not-a-real-version",
                )
        self.assertEqual(ctx.exception.code, "UPGRADE_TARGET_NOT_AVAILABLE")

    @mock.patch("commands.upgrade_executor.upgrade_registry.manifest_probe")
    def test_immutable_target_rejects_moved_tag(self, probe):
        probe.return_value = upgrade_registry.RemoteProbe("sha256:bbbb", "ok")
        with self.assertRaises(upgrade_executor.UpgradeExecutionError) as ctx:
            upgrade_executor._verify_selected_digest(
                "stack6/hermes",
                "nousresearch/hermes-agent:v2026.9.11",
                {
                    "target_image": "nousresearch/hermes-agent:v2026.9.11",
                    "target_digest": "sha256:aaaa",
                },
            )
        self.assertEqual(ctx.exception.code, "UPGRADE_TARGET_MOVED")

    @mock.patch("commands.upgrade_executor._run")
    def test_recovery_point_consumes_backup_set_json_field(self, run):
        run.return_value = subprocess.CompletedProcess(
            [], 0, json.dumps({"backup_set": "/opt/local-hybrid-ai-backups/backup-test"}), ""
        )
        root = Path("/opt/docker/stacks")
        result = upgrade_executor._recovery_point(root)
        self.assertEqual(result, "/opt/local-hybrid-ai-backups/backup-test")
        command = run.call_args.args[0]
        self.assertEqual(command[1], str(root / "commands" / "recovery" / "backup-all.py"))
        self.assertEqual(command[2], "--json")

    def test_execution_rejects_empty_selection_before_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime"
            (root / ".env").write_text("OPENWEBUI_VERSION=v0.11.3\n", encoding="utf-8")
            with self.assertRaises(upgrade_executor.UpgradeExecutionError) as ctx:
                upgrade_executor.execute(
                    root=root,
                    runtime_root=runtime,
                    selections=[],
                    components={},
                    plan_path=runtime / "platform" / "upgrade-plan.json",
                )
            self.assertEqual(ctx.exception.code, "UPGRADE_NOTHING_SELECTED")

    @mock.patch("commands.upgrade_executor.os.geteuid", return_value=0)
    def test_executor_revalidates_policy_before_target_preflight_or_mutation(self, _geteuid):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime"
            (root / "commands").mkdir()
            (root / "commands" / "install-lifecycle.json").write_text('{"stacks":{}}', encoding="utf-8")
            (root / ".env").write_text(
                "APP_IMAGE=example/app\nAPP_VERSION=1.27.1\n",
                encoding="utf-8",
            )
            selection = {
                "stack": "stack4",
                "component": "app",
                "current_at_selection": "1.27.1",
                "version": "1.28.0",
            }
            component = {
                "id": "app",
                "stack": "stack4",
                "selectable": True,
                "default_policy": "minor-series",
                "apply": {
                    "type": "env-version",
                    "env_key": "APP_VERSION",
                    "image_env_key": "APP_IMAGE",
                    "deploy": ["docker", "compose", "up", "-d", "app"],
                },
            }
            with self.assertRaises(upgrade_executor.UpgradeExecutionError) as ctx:
                upgrade_executor.execute(
                    root=root,
                    runtime_root=runtime,
                    selections=[selection],
                    components={"stack4/app": component},
                    plan_path=runtime / "platform" / "upgrade-plan.json",
                )
            self.assertEqual(ctx.exception.code, "UPGRADE_TARGET_UNSUPPORTED")
            self.assertIn("APP_VERSION=1.27.1", (root / ".env").read_text())


if __name__ == "__main__":
    unittest.main()
