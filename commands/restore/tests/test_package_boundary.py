# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
from __future__ import annotations

import inspect
import unittest
from pathlib import Path

import commands.restore.api as api


class RestorePackageBoundaryTests(unittest.TestCase):
    def test_public_api_is_package_owned(self):
        self.assertTrue(Path(inspect.getfile(api)).resolve().parent.name == "restore")

    def test_restore_tree_does_not_import_recovery_package(self):
        root = Path(inspect.getfile(api)).resolve().parent
        offenders = []
        for path in sorted(root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            if "commands.recovery" in source:
                offenders.append(str(path.relative_to(root)))
        self.assertEqual([], offenders)

    def test_restore_implementation_is_package_owned(self):
        root = Path(inspect.getfile(api)).resolve().parent
        for name in (
            "dr.py",
            "dr_preflight.py",
            "dr_restore_all.py",
            "dr_restore_drill.py",
            "dr_restore_live_service.py",
            "dr_restore_managed.py",
            "dr_restore_resume.py",
            "dr_restore_stage.py",
            "dr_stack4_backup.py",
        ):
            self.assertTrue((root / name).is_file(), name)

    def test_restore_dr_uses_repository_root(self):
        root = Path(inspect.getfile(api)).resolve().parent
        source = (root / "dr.py").read_text(encoding="utf-8")
        self.assertIn('Path(__file__).resolve().parents[2]', source)
        self.assertIn('ROOT / "stack0_-_platform" / "manifests.py"', source)

    def test_public_surface_is_complete(self):
        for name in (
            "plan_payload",
            "drill_payload",
            "check_clean_target_payload",
            "apply_payload",
            "resume_payload",
            "cli_text",
        ):
            self.assertTrue(callable(getattr(api, name, None)), name)


if __name__ == "__main__":
    unittest.main()
