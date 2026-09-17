# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Package-boundary tests for the backup command package."""
from pathlib import Path
import unittest


class BackupPackageBoundaryTests(unittest.TestCase):
    def test_backup_package_owns_execution_graph(self):
        root = Path(__file__).resolve().parents[1]
        required = {
            "dr.py", "dr_preflight.py", "dr_archive.py", "dr_filesystem.py",
            "dr_postgres_verify.py", "dr_stack3_backup.py", "dr_stack4_backup.py",
            "dr_backup_all.py", "backup-set.schema.json",
        }
        self.assertTrue(required.issubset({p.name for p in root.iterdir()}))

    def test_public_api_does_not_import_recovery_package(self):
        text = (Path(__file__).resolve().parents[1] / "api.py").read_text(encoding="utf-8")
        self.assertNotIn("commands.recovery", text)
        self.assertNotIn("recovery.public_api", text)

    def test_backup_payload_is_package_owned(self):
        from commands.backup import api
        self.assertEqual("commands.backup.api", api.__name__)
        self.assertTrue(callable(api.backup_payload))

    def test_package_env_points_to_project_env(self):
        link = Path(__file__).resolve().parents[1] / ".env"
        self.assertTrue(link.is_symlink())
        self.assertEqual("../../.env", str(link.readlink()))


if __name__ == "__main__":
    unittest.main()
