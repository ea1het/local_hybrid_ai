# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Package-boundary tests for the backup command package."""
from pathlib import Path
import unittest

PACKAGES_ROOT = Path(__file__).resolve().parents[2] / "src" / "local_ai_cli"
BACKUP_DIR = PACKAGES_ROOT / "backup"


class BackupPackageBoundaryTests(unittest.TestCase):
    def test_backup_package_owns_execution_graph(self):
        required = {
            "planner.py", "stack3_backup.py", "stack4_backup.py", "backup_all.py",
        }
        self.assertTrue(required.issubset({p.name for p in BACKUP_DIR.iterdir()}))

    def test_shared_dr_primitives_are_core_owned(self):
        common = PACKAGES_ROOT / "common"
        required = {"preflight.py", "archive.py", "filesystem.py", "postgres.py", "backup-set.schema.json"}
        self.assertTrue(required.issubset({p.name for p in common.iterdir()}))

    def test_public_api_does_not_import_recovery_package(self):
        text = (BACKUP_DIR / "api.py").read_text(encoding="utf-8")
        self.assertNotIn("local_ai_cli.recovery", text)
        self.assertNotIn("recovery.public_api", text)

    def test_backup_payload_is_package_owned(self):
        from local_ai_cli.backup import api
        self.assertEqual("local_ai_cli.backup.api", api.__name__)
        self.assertTrue(callable(api.backup_payload))

    def test_package_env_points_to_project_env(self):
        link = BACKUP_DIR / ".env"
        self.assertTrue(link.is_symlink())
        self.assertEqual("../../../.env", str(link.readlink()))


if __name__ == "__main__":
    unittest.main()
