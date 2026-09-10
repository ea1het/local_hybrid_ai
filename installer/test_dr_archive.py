import datetime as dt
import hashlib
import importlib.util
import json
import os
import stat
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "dr_archive.py"
SPEC = importlib.util.spec_from_file_location("dr_archive", MODULE_PATH)
dr_archive = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(dr_archive)


class DisasterRecoveryArchiveTests(unittest.TestCase):
    def make_source(self, parent: Path) -> Path:
        source = parent / "pki"
        source.mkdir(mode=0o700)
        key = source / "tls.key"
        cert = source / "tls.crt"
        key.write_text("PRIVATE-KEY-TEST\n", encoding="utf-8")
        cert.write_text("CERTIFICATE-TEST\n", encoding="utf-8")
        os.chmod(key, 0o640)
        os.chmod(cert, 0o644)
        return source

    def make_root(self, parent: Path) -> Path:
        root = parent / "backups"
        root.mkdir(mode=0o700)
        os.chmod(root, 0o700)
        return root

    def artifact(self) -> dr_archive.ArchiveArtifact:
        return dr_archive.ArchiveArtifact(
            stack_id=0,
            resource_id="platform-pki",
            strategy="archive",
            sensitive=True,
            restore_phase="pre-prepare",
            relative_path="artifacts/stack0/platform-pki.tar",
        )

    def execute(self, root: Path, source: Path, when: dt.datetime | None = None):
        return dr_archive.execute_archive_backup_set(
            backup_root=root,
            source=source,
            source_commit="a" * 40,
            requested=["0"],
            resolved_stacks=[0],
            artifact=self.artifact(),
            prerequisites=[],
            now=when or dt.datetime(2026, 9, 10, 15, 0, 0, tzinfo=dt.timezone.utc),
        )

    def test_completed_set_has_expected_private_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            source = self.make_source(parent)
            root = self.make_root(parent)
            result = self.execute(root, source)

            self.assertEqual(result.path.name, "backup-20260910T150000Z")
            self.assertTrue(result.artifact_path.is_file())
            self.assertTrue(result.metadata_path.is_file())
            self.assertTrue(result.checksums_path.is_file())
            self.assertEqual(stat.S_IMODE(result.path.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(result.artifact_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(result.metadata_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(result.checksums_path.stat().st_mode), 0o600)

    def test_archive_contains_bounded_source_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            source = self.make_source(parent)
            root = self.make_root(parent)
            result = self.execute(root, source)

            with tarfile.open(result.artifact_path, "r") as archive:
                names = set(archive.getnames())
            self.assertIn("pki", names)
            self.assertIn("pki/tls.key", names)
            self.assertIn("pki/tls.crt", names)
            self.assertTrue(all(not name.startswith("/") for name in names))
            self.assertTrue(all(".." not in Path(name).parts for name in names))

    def test_metadata_and_checksum_index_match_real_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            source = self.make_source(parent)
            root = self.make_root(parent)
            result = self.execute(root, source)

            metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
            dr_archive.validate_completed_metadata(metadata)
            artifact = metadata["artifacts"][0]
            self.assertEqual(artifact["sha256"], dr_archive.sha256_file(result.artifact_path))
            self.assertEqual(artifact["size_bytes"], result.artifact_path.stat().st_size)

            index = result.checksums_path.read_text(encoding="utf-8")
            metadata_hash = hashlib.sha256(result.metadata_path.read_bytes()).hexdigest()
            self.assertIn(f"{artifact['sha256']}  artifacts/stack0/platform-pki.tar", index)
            self.assertIn(f"{metadata_hash}  backup.json", index)

    def test_existing_final_name_fails_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            source = self.make_source(parent)
            root = self.make_root(parent)
            existing = root / "backup-20260910T150000Z"
            existing.mkdir(mode=0o700)
            sentinel = existing / "sentinel"
            sentinel.write_text("keep", encoding="utf-8")

            with self.assertRaises(dr_archive.ArchiveBackupError):
                self.execute(root, source)

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
            self.assertEqual(
                [p.name for p in root.iterdir() if p.name.startswith(".backup-")],
                [],
            )

    def test_source_files_are_not_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            source = self.make_source(parent)
            root = self.make_root(parent)
            before = {
                path.name: (path.stat().st_ino, stat.S_IMODE(path.stat().st_mode), hashlib.sha256(path.read_bytes()).hexdigest())
                for path in source.iterdir()
            }

            self.execute(root, source)

            after = {
                path.name: (path.stat().st_ino, stat.S_IMODE(path.stat().st_mode), hashlib.sha256(path.read_bytes()).hexdigest())
                for path in source.iterdir()
            }
            self.assertEqual(before, after)

    def test_malformed_metadata_is_rejected_against_schema_contract(self):
        metadata = {
            "schema_version": 1,
            "kind": "local-hybrid-ai-backup-set",
            "created_at": "2026-09-10T15:00:00Z",
            "source_commit": "a" * 40,
            "requested": ["0"],
            "resolved_stacks": [0],
            "artifacts": [{
                "stack_id": 0,
                "resource_id": "platform-pki",
                "strategy": "archive",
                "sensitive": True,
                "restore_phase": "pre-prepare",
                "relative_path": "artifacts/stack0/platform-pki.tar",
                "sha256": "not-a-hash",
                "size_bytes": 1,
            }],
            "prerequisites": [],
        }
        with self.assertRaises(dr_archive.ArchiveBackupError):
            dr_archive.validate_completed_metadata(metadata)

    def test_real_milestone_gate_rejects_non_stack0_dependency_plan(self):
        manifests = {
            0: {
                "recovery": {
                    "resources": [{
                        "id": "platform-pki",
                        "strategy": "archive",
                        "sensitive": True,
                        "config": {
                            "source": {"path": "${BASE_PATH}/service_-_platform/pki"},
                            "restore": {"phase": "pre-prepare"},
                        },
                    }]
                }
            }
        }
        with self.assertRaises(dr_archive.ArchiveBackupError):
            dr_archive.select_stack0_archive(manifests, [0, 1])


if __name__ == "__main__":
    unittest.main()
