#!/usr/bin/env python3
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

from local_ai_cli.upgrade import engine as upgrade_executor, _registry as upgrade_registry


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

    @mock.patch("local_ai_cli.upgrade.engine.subprocess.run")
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

    @mock.patch("local_ai_cli.upgrade.engine.subprocess.run")
    def test_target_image_preflight_rejects_missing_image(self, run):
        run.return_value = subprocess.CompletedProcess([], 1, "", "manifest unknown")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(upgrade_executor.UpgradeExecutionError) as ctx:
                upgrade_executor._preflight_target_image(
                    Path(tmp),
                    "nousresearch/hermes-agent:not-a-real-version",
                )
        self.assertEqual(ctx.exception.code, "UPGRADE_TARGET_NOT_AVAILABLE")

    @mock.patch("local_ai_cli.upgrade.engine.upgrade_registry.manifest_probe")
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

    @mock.patch("local_ai_cli.upgrade.engine.upgrade_backup.backup_payload")
    def test_recovery_point_consumes_backup_set_result_field(self, backup_payload):
        backup_payload.return_value = {
            "schema_version": "1",
            "command": "backup",
            "success": True,
            "result": {"backup_set": "/opt/local-hybrid-ai-backups/backup-test"},
        }
        result = upgrade_executor._recovery_point()
        self.assertEqual(result, "/opt/local-hybrid-ai-backups/backup-test")
        backup_payload.assert_called_once_with()

    @mock.patch("local_ai_cli.upgrade.engine.upgrade_backup.backup_payload")
    def test_recovery_point_surfaces_backup_engine_failure(self, backup_payload):
        backup_payload.return_value = {
            "schema_version": "1",
            "command": "backup",
            "success": False,
            "error": {"code": "BACKUP_FAILED", "message": "destination is not writable"},
        }
        with self.assertRaises(upgrade_executor.UpgradeExecutionError) as ctx:
            upgrade_executor._recovery_point()
        self.assertEqual(ctx.exception.code, "UPGRADE_BACKUP_FAILED")

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

    @mock.patch("local_ai_cli.upgrade.engine.os.geteuid", return_value=0)
    def test_executor_revalidates_policy_before_target_preflight_or_mutation(self, _geteuid):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime"
            (root / "src" / "local_ai_cli").mkdir(parents=True)
            (root / "src" / "local_ai_cli" / "install-lifecycle.json").write_text('{"stacks":{}}', encoding="utf-8")
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

    def _postgres_component(self):
        return {
            "id": "postgresql",
            "stack": "stack3",
            "container": "litellm-postgres",
            "selectable": True,
            "default_policy": "major-series",
            "recovery_required": False,
            "apply": {
                "type": "postgres-major-upgrade",
                "image_env_key": "LITELLM_POSTGRES_IMAGE",
                "database_env": "LITELLM_DB_NAME",
                "role_env": "LITELLM_DB_USER",
                "data_path_env": "BASE_PATH",
                "data_relative_path": "service_-_litellm-postgres/data",
                "dependent_containers": ["litellm"],
                "deploy": ["./02-postgres.sh"],
            },
        }

    def _postgres_selection(self):
        return {
            "stack": "stack3",
            "component": "postgresql",
            "current_at_selection": "17.10-alpine",
            "version": "17.11-alpine",
            "target_image": "postgres:17.11-alpine",
            "target_digest": "sha256:" + "a" * 64,
        }

    @mock.patch("local_ai_cli.upgrade.engine.os.geteuid", return_value=0)
    def test_data_migration_selection_must_be_isolated(self, _geteuid):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("LITELLM_POSTGRES_IMAGE=postgres:17.10-alpine\n", encoding="utf-8")
            (root / "src" / "local_ai_cli").mkdir(parents=True)
            (root / "src" / "local_ai_cli" / "install-lifecycle.json").write_text('{"stacks":{}}', encoding="utf-8")
            other_selection = {"stack": "stack7", "component": "open-webui", "current_at_selection": "v0.11.3", "version": "v0.11.4"}
            with self.assertRaises(upgrade_executor.UpgradeExecutionError) as ctx:
                upgrade_executor.execute(
                    root=root, runtime_root=root / "runtime",
                    selections=[self._postgres_selection(), other_selection],
                    components={"stack3/postgresql": self._postgres_component()},
                    plan_path=root / "runtime" / "platform" / "upgrade-plan.json",
                )
            self.assertEqual(ctx.exception.code, "UPGRADE_DATA_MIGRATION_MUST_BE_ISOLATED")

    @mock.patch("local_ai_cli.upgrade.engine.os.geteuid", return_value=0)
    def test_data_migration_requires_explicit_confirmation(self, _geteuid):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("LITELLM_POSTGRES_IMAGE=postgres:17.10-alpine\n", encoding="utf-8")
            (root / "src" / "local_ai_cli").mkdir(parents=True)
            (root / "src" / "local_ai_cli" / "install-lifecycle.json").write_text('{"stacks":{}}', encoding="utf-8")
            with self.assertRaises(upgrade_executor.UpgradeExecutionError) as ctx:
                upgrade_executor.execute(
                    root=root, runtime_root=root / "runtime",
                    selections=[self._postgres_selection()],
                    components={"stack3/postgresql": self._postgres_component()},
                    plan_path=root / "runtime" / "platform" / "upgrade-plan.json",
                )
            self.assertEqual(ctx.exception.code, "UPGRADE_DATA_MIGRATION_CONFIRMATION_REQUIRED")

    @mock.patch("local_ai_cli.upgrade.engine.os.geteuid", return_value=0)
    @mock.patch("local_ai_cli.upgrade.engine.upgrade_postgres_migration.execute")
    @mock.patch("local_ai_cli.upgrade.engine.subprocess.run")
    @mock.patch("local_ai_cli.upgrade.engine.upgrade_registry.manifest_probe")
    @mock.patch("local_ai_cli.upgrade.engine._version_from_image", return_value="17.11-alpine")
    @mock.patch("local_ai_cli.upgrade.engine._running_image", return_value="postgres:17.11-alpine")
    @mock.patch("local_ai_cli.upgrade.engine._run_commands")
    @mock.patch("local_ai_cli.upgrade.engine._wait_ready")
    @mock.patch("local_ai_cli.upgrade.engine._load_manifests", return_value={3: {"provides": [], "requires": [], "optional": [], "consumes": [], "optional_consumes": []}})
    def test_data_migration_dispatches_to_dedicated_module(
        self, _load_manifests, _wait_ready, _run_commands, _running_image, _version_from_image, manifest_probe, subprocess_run, migration_execute, _geteuid,
    ):
        manifest_probe.return_value = upgrade_registry.RemoteProbe("sha256:" + "a" * 64, "ok")
        subprocess_run.return_value = subprocess.CompletedProcess([], 0, "", "")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("LITELLM_POSTGRES_IMAGE=postgres:17.10-alpine\n", encoding="utf-8")
            (root / "src" / "local_ai_cli").mkdir(parents=True)
            lifecycle = {"stacks": {"3": {"directory": "stack3_-_litellm", "required_containers": ["litellm-postgres"], "reconcile": [], "verify": []}}}
            (root / "src" / "local_ai_cli" / "install-lifecycle.json").write_text(json.dumps(lifecycle), encoding="utf-8")
            runtime_root = root / "runtime"
            plan_path = runtime_root / "platform" / "upgrade-plan.json"
            plan_path.parent.mkdir(parents=True); plan_path.write_text('{"schema_version":1,"selected":{}}', encoding="utf-8")
            result = upgrade_executor.execute(
                root=root, runtime_root=runtime_root,
                selections=[self._postgres_selection()],
                components={"stack3/postgresql": self._postgres_component()},
                plan_path=plan_path, quiet=True, confirm_data_migration=True,
            )
        migration_execute.assert_called_once()
        _, kwargs = migration_execute.call_args
        self.assertEqual(kwargs["component_key"], "stack3/postgresql")
        self.assertEqual(kwargs["container"], "litellm-postgres")
        self.assertEqual(kwargs["target_image_ref"], "postgres:17.11-alpine")
        self.assertTrue(result["success"] if "success" in result else True)


if __name__ == "__main__":
    unittest.main()
