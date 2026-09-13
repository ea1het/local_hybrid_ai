from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from commands import upgrade, upgrade_entry
from internal import container_registry, upgrade_policy


class UpgradeSelectionPolicyTests(unittest.TestCase):
    def _runtime_patches(self, runtime: Path):
        return (
            mock.patch.object(upgrade, "runtime_root", return_value=runtime),
            mock.patch.object(
                upgrade,
                "running_image",
                return_value="ghcr.io/open-webui/open-webui:v0.11.3",
            ),
        )

    def test_select_persists_newer_target_inside_minor_series(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            runtime_patch, image_patch = self._runtime_patches(runtime)
            with runtime_patch, image_patch, mock.patch.object(
                container_registry,
                "manifest_probe",
                return_value=container_registry.RemoteProbe("sha256:" + "a" * 64, "ok"),
            ):
                rc = upgrade_entry.select("stack7", None, "v0.11.4")
            self.assertEqual(rc, 0)
            plan = json.loads((runtime / "platform" / "upgrade-plan.json").read_text())
            selected = plan["selected"]["stack7/open-webui"]
            self.assertEqual(selected["version"], "v0.11.4")
            self.assertEqual(selected["policy_at_selection"], "minor-series")

    def test_select_rejects_target_outside_effective_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            runtime_patch, image_patch = self._runtime_patches(runtime)
            with runtime_patch, image_patch, mock.patch.object(
                container_registry,
                "manifest_probe",
                return_value=container_registry.RemoteProbe("sha256:" + "b" * 64, "ok"),
            ):
                with self.assertRaises(upgrade.UpgradeError) as ctx:
                    upgrade_entry.select("stack7", None, "v0.12.0")
            self.assertEqual(ctx.exception.code, "UPGRADE_TARGET_UNSUPPORTED")
            self.assertFalse((runtime / "platform" / "upgrade-plan.json").exists())

    def test_select_rejects_target_missing_from_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            runtime_patch, image_patch = self._runtime_patches(runtime)
            with runtime_patch, image_patch, mock.patch.object(
                container_registry,
                "manifest_probe",
                return_value=container_registry.RemoteProbe(None, "not_found"),
            ):
                with self.assertRaises(upgrade.UpgradeError) as ctx:
                    upgrade_entry.select("stack7", None, "v0.11.99")
            self.assertEqual(ctx.exception.code, "UPGRADE_TARGET_NOT_AVAILABLE")

    def test_manual_override_allows_explicit_newer_target_outside_minor_series(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            upgrade_policy.set_override(runtime, "stack7/open-webui", "manual")
            runtime_patch, image_patch = self._runtime_patches(runtime)
            with runtime_patch, image_patch, mock.patch.object(
                container_registry,
                "manifest_probe",
                return_value=container_registry.RemoteProbe("sha256:" + "c" * 64, "ok"),
            ):
                rc = upgrade_entry.select("stack7", None, "v0.12.0")
            self.assertEqual(rc, 0)
            plan = json.loads((runtime / "platform" / "upgrade-plan.json").read_text())
            self.assertEqual(plan["selected"]["stack7/open-webui"]["policy_at_selection"], "manual")


if __name__ == "__main__":
    unittest.main()
