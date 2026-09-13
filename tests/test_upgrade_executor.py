from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from internal import upgrade_executor


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

    @mock.patch("internal.upgrade_executor.subprocess.run")
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

    @mock.patch("internal.upgrade_executor.subprocess.run")
    def test_target_image_preflight_rejects_missing_image(self, run):
        run.return_value = subprocess.CompletedProcess([], 1, "", "manifest unknown")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(upgrade_executor.UpgradeExecutionError) as ctx:
                upgrade_executor._preflight_target_image(
                    Path(tmp),
                    "nousresearch/hermes-agent:not-a-real-version",
                )
        self.assertEqual(ctx.exception.code, "UPGRADE_TARGET_UNAVAILABLE")

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


if __name__ == "__main__":
    unittest.main()
