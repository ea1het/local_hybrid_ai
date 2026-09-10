import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

import dr_stack4_restore_verify


class Stack4RestoreVerifyTests(unittest.TestCase):
    def test_safe_zip_kind_rejects_symlink(self):
        info = zipfile.ZipInfo("repos/u/r.git/link")
        info.create_system = 3
        info.external_attr = (0o120777 << 16)
        with self.assertRaises(dr_stack4_restore_verify.Stack4RestoreVerifyError):
            dr_stack4_restore_verify.safe_zip_kind(info)

    def test_restore_sqlite_imports_tables_and_data(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sql = root / "gitea-db.sql"
            sql.write_text(
                "CREATE TABLE user(id INTEGER PRIMARY KEY, name TEXT);"
                "INSERT INTO user(name) VALUES ('alice');"
                "CREATE TABLE repo(id INTEGER PRIMARY KEY, name TEXT);",
                encoding="utf-8",
            )
            tables, nonempty = dr_stack4_restore_verify.restore_sqlite(sql, root / "restored.db")
            self.assertEqual(tables, 2)
            self.assertEqual(nonempty, 1)

    def test_safe_extract_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "gitea.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("../escape", "x")
            target = root / "out"
            target.mkdir()
            with self.assertRaises(Exception):
                dr_stack4_restore_verify.safe_extract_gitea_dump(archive, target)

    def test_find_bare_repositories(self):
        with tempfile.TemporaryDirectory() as td:
            repos = Path(td) / "repos"
            repo = repos / "alice" / "demo.git"
            repo.mkdir(parents=True)
            (repo / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
            found = dr_stack4_restore_verify.find_bare_repositories(repos)
            self.assertEqual(found, [repo])

    def test_result_never_claims_live_modification(self):
        result = dr_stack4_restore_verify.RestoreVerification(
            backup_set=Path("/tmp/example"),
            zip_members=1,
            sqlite_tables=1,
            sqlite_nonempty_tables=1,
            repositories=1,
            repositories_fsck_passed=1,
            temporary_restore_removed=True,
        ).as_dict()
        self.assertFalse(result["live_gitea_runtime_modified"])
        self.assertFalse(result["live_gitea_container_restarted"])


if __name__ == "__main__":
    unittest.main()
