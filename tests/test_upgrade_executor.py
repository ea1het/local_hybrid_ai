from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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
