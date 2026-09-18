#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Package-boundary tests for the restore command package."""
from __future__ import annotations

import inspect
import unittest
from pathlib import Path

import local_ai_cli.restore.api as api


class RestorePackageBoundaryTests(unittest.TestCase):
    def test_public_api_is_package_owned(self):
        self.assertTrue(Path(inspect.getfile(api)).resolve().parent.name == "restore")

    def test_restore_tree_does_not_import_recovery_package(self):
        root = Path(inspect.getfile(api)).resolve().parent
        offenders = []
        for path in sorted(root.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            forbidden = "local_ai_cli." + "recovery"
            if forbidden in source:
                offenders.append(path.name)
        self.assertEqual([], offenders)

    def test_restore_implementation_is_package_owned(self):
        root = Path(inspect.getfile(api)).resolve().parent
        for name in (
            "planner.py",
            "restore_all.py",
            "restore_drill.py",
            "restore_live_service.py",
            "restore_managed.py",
            "restore_resume.py",
            "restore_stage.py",
            "stack4_dump_validation.py",
        ):
            self.assertTrue((root / name).is_file(), name)

    def test_shared_dr_primitives_are_core_owned(self):
        common = Path(inspect.getfile(api)).resolve().parents[1] / "common"
        for name in ("archive.py", "preflight.py"):
            self.assertTrue((common / name).is_file(), name)

    def test_restore_dr_uses_repository_root(self):
        root = Path(inspect.getfile(api)).resolve().parent
        source = (root / "planner.py").read_text(encoding="utf-8")
        self.assertIn('Path(__file__).resolve().parents[3]', source)
        self.assertIn('ROOT / "stack0_-_platform" / "manifests.py"', source)

    def test_public_surface_is_complete(self):
        for name in (
            "list_backup_sets_payload",
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
