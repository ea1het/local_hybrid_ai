import tempfile
import unittest
import zipfile
from pathlib import Path

import dr_stack4_restore_verify


class Stack4RestoreVerifyTests(unittest.TestCase):
    def test_safe_zip_kind_accepts_regular_file(self):
        info = zipfile.ZipInfo("gitea-db.sql")
        self.assertEqual(dr_stack4_restore_verify.safe_zip_kind(info), "file")

    def test_safe_extract_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "bad.zip"
            destination = Path(td) / "restore"
            destination.mkdir()
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("../escape", "x")
            with self.assertRaises(Exception):
                dr_stack4_restore_verify.safe_extract_gitea_dump(archive, destination)

    def test_restore_sqlite_imports_tables_and_data(self):
        with tempfile.TemporaryDirectory() as td:
            sql_path = Path(td) / "gitea-db.sql"
            db_path = Path(td) / "gitea.db"
            sql_path.write_text(
                "CREATE TABLE user (id INTEGER PRIMARY KEY, name TEXT);"
                "INSERT INTO user(name) VALUES ('alice');",
                encoding="utf-8",
            )
            tables, nonempty = dr_stack4_restore_verify.restore_sqlite(sql_path, db_path)
            self.assertEqual(tables, 1)
            self.assertEqual(nonempty, 1)

    def test_find_bare_repositories_requires_repo(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(dr_stack4_restore_verify.Stack4RestoreVerifyError):
                dr_stack4_restore_verify.find_bare_repositories(root)

    def test_find_bare_repositories_finds_git_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "owner" / "demo.git"
            repo.mkdir(parents=True)
            (repo / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
            found = dr_stack4_restore_verify.find_bare_repositories(root)
            self.assertEqual(found, [repo])


if __name__ == "__main__":
    unittest.main()
