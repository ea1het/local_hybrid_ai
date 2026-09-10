import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import dr_archive
import dr_archive_restore


class DisasterRecoveryArchiveRestoreTests(unittest.TestCase):
    def make_source(self, parent: Path) -> Path:
        source = parent / "pki"
        source.mkdir(mode=0o700)
        (source / "tls.key").write_text("PRIVATE-KEY-TEST\n", encoding="utf-8")
        (source / "tls.crt").write_text("CERTIFICATE-TEST\n", encoding="utf-8")
        os.chmod(source / "tls.key", 0o640)
        os.chmod(source / "tls.crt", 0o644)
        return source

    def make_backup(self, parent: Path, source: Path) -> Path:
        root = parent / "backups"
        root.mkdir(mode=0o700)
        os.chmod(root, 0o700)
        artifact = dr_archive.ArchiveArtifact(
            stack_id=0,
            resource_id="platform-pki",
            strategy="archive",
            sensitive=True,
            restore_phase="pre-prepare",
            relative_path="artifacts/stack0/platform-pki.tar",
        )
        result = dr_archive.execute_archive_backup_set(
            backup_root=root,
            source=source,
            source_commit="a" * 40,
            requested=["0"],
            resolved_stacks=[0],
            artifact=artifact,
            prerequisites=[],
            now=dt.datetime(2026, 9, 10, 15, 0, 0, tzinfo=dt.timezone.utc),
        )
        return result.path

    def test_restore_verification_matches_source_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            source = self.make_source(parent)
            backup_set = self.make_backup(parent, source)
            result = dr_archive_restore.verify_restore(backup_set, compare_source=source)
            self.assertTrue(result.source_match)
            self.assertTrue(result.temporary_cleanup)
            self.assertEqual(result.member_count, 3)

    def test_checksum_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            source = self.make_source(parent)
            backup_set = self.make_backup(parent, source)
            artifact = backup_set / "artifacts/stack0/platform-pki.tar"
            with artifact.open("ab") as handle:
                handle.write(b"tamper")
            with self.assertRaises(dr_archive_restore.ArchiveRestoreError):
                dr_archive_restore.verify_restore(backup_set, compare_source=source)

    def test_source_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            source = self.make_source(parent)
            backup_set = self.make_backup(parent, source)
            (source / "tls.crt").write_text("CHANGED\n", encoding="utf-8")
            with self.assertRaises(dr_archive_restore.ArchiveRestoreError):
                dr_archive_restore.verify_restore(backup_set, compare_source=source)

    def test_path_traversal_member_name_is_rejected(self):
        with self.assertRaises(dr_archive_restore.ArchiveRestoreError):
            dr_archive_restore.safe_member_name("../escape")
        with self.assertRaises(dr_archive_restore.ArchiveRestoreError):
            dr_archive_restore.safe_member_name("/absolute")
        with self.assertRaises(dr_archive_restore.ArchiveRestoreError):
            dr_archive_restore.safe_member_name("other/file")

    def test_absolute_symlink_target_is_rejected(self):
        with self.assertRaises(dr_archive_restore.ArchiveRestoreError):
            dr_archive_restore.validate_symlink_target(
                dr_archive_restore.PurePosixPath("pki/link"), "/etc/passwd"
            )

    def test_result_json_never_claims_live_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            source = self.make_source(parent)
            backup_set = self.make_backup(parent, source)
            payload = dr_archive_restore.verify_restore(backup_set, compare_source=source).as_dict()
            self.assertFalse(payload["live_runtime_modified"])
            self.assertTrue(payload["temporary_cleanup"])
            self.assertTrue(payload["source_match"])
            json.dumps(payload)


if __name__ == "__main__":
    unittest.main()
