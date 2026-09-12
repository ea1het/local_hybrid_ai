import tempfile
import unittest
import zipfile
from pathlib import Path

import dr_stack4_backup
import dr_stack4_inspect


class Stack4BackupAdapterTests(unittest.TestCase):
    def test_validate_zip_member_accepts_relative_paths(self):
        for name in ("gitea-db.sql", "repos/user/repo.git/HEAD", "data/attachments/a"):
            dr_stack4_backup.validate_zip_member(name)

    def test_validate_zip_member_rejects_unsafe_paths(self):
        for name in ("/absolute", "../escape", "x/../../escape", "bad\\path"):
            with self.assertRaises(dr_stack4_backup.Stack4BackupError):
                dr_stack4_backup.validate_zip_member(name)

    def test_validate_gitea_dump_checks_zip_integrity(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "gitea.zip"
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr("gitea-db.sql", "SELECT 1;")
                zf.writestr("repos/user/repo.git/HEAD", "ref: refs/heads/main\n")
            names = dr_stack4_backup.validate_gitea_dump(path)
            self.assertIn("gitea-db.sql", names)
            self.assertIn("repos/user/repo.git/HEAD", names)

    def test_validate_gitea_dump_rejects_non_zip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "gitea.zip"
            path.write_bytes(b"not a zip")
            with self.assertRaises(dr_stack4_backup.Stack4BackupError):
                dr_stack4_backup.validate_gitea_dump(path)

    def test_classify_members_finds_recovery_categories(self):
        counts = dr_stack4_inspect.classify_members([
            "gitea-db.sql",
            "repos/u/r.git/HEAD",
            "data/lfs/objects/x",
            "data/attachments/y",
            "data/packages/z",
            "custom/conf/app.ini",
        ])
        self.assertGreaterEqual(counts["database_like"], 1)
        self.assertGreaterEqual(counts["repositories_like"], 1)
        self.assertGreaterEqual(counts["lfs_like"], 1)
        self.assertGreaterEqual(counts["attachments_like"], 1)
        self.assertGreaterEqual(counts["packages_like"], 1)
        self.assertGreaterEqual(counts["custom_config_like"], 1)

    def test_select_resources_requires_dependency_complete_stack4_plan(self):
        manifests = {
            0: {"recovery": {"resources": [{"id": "platform-pki", "strategy": "archive"}]}},
            4: {"recovery": {"resources": [{"id": "gitea-state", "strategy": "gitea-native-dump"}]}},
        }
        pki, gitea = dr_stack4_backup.select_resources(manifests, [0, 4])
        self.assertEqual(pki["id"], "platform-pki")
        self.assertEqual(gitea["id"], "gitea-state")
        with self.assertRaises(dr_stack4_backup.Stack4BackupError):
            dr_stack4_backup.select_resources(manifests, [4])


if __name__ == "__main__":
    unittest.main()
