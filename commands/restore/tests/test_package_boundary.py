# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path

import commands.restore.api as api


class RestorePackageBoundaryTests(unittest.TestCase):
    def test_public_api_is_package_owned(self):
        self.assertEqual("restore", Path(inspect.getfile(api)).resolve().parent.name)

    def test_restore_tree_does_not_import_recovery_package(self):
        root = Path(inspect.getfile(api)).resolve().parent
        offenders = []
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    if any(alias.name == "commands.recovery" or alias.name.startswith("commands.recovery.") for alias in node.names):
                        offenders.append(str(path.relative_to(root)))
                        break
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if module == "commands.recovery" or module.startswith("commands.recovery."):
                        offenders.append(str(path.relative_to(root)))
                        break
        self.assertEqual([], offenders)

    def test_restore_implementation_is_package_owned(self):
        root = Path(inspect.getfile(api)).resolve().parent
        for name in (
            "dr.py",
            "dr_archive.py",
            "dr_archive_restore.py",
            "dr_filesystem.py",
            "dr_postgres_artifact_verify.py",
            "dr_preflight.py",
            "dr_restore_all.py",
            "dr_restore_compat.py",
            "dr_restore_drill.py",
            "dr_restore_live.py",
            "dr_restore_live_service.py",
            "dr_restore_managed.py",
            "dr_restore_resume.py",
            "dr_restore_stage.py",
            "dr_stack3_restore_verify.py",
            "dr_stack4_backup.py",
            "dr_stack4_inspect.py",
            "dr_stack4_restore_verify.py",
            "dr_stack6_verify.py",
        ):
            self.assertTrue((root / name).is_file(), name)

    def test_restore_dr_uses_repository_root(self):
        root = Path(inspect.getfile(api)).resolve().parent
        source = (root / "dr.py").read_text(encoding="utf-8")
        self.assertIn('Path(__file__).resolve().parents[2]', source)
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
