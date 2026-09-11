import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import dr_archive
import dr_postgres_artifact_verify
import dr_stack4_inspect


class FullBackupSetCompatibilityTests(unittest.TestCase):
    def metadata(self):
        return {
            "schema_version": 1,
            "kind": "local-hybrid-ai-backup-set",
            "created_at": "2026-09-11T00:49:27Z",
            "source_commit": "a" * 40,
            "requested": ["all"],
            "resolved_stacks": [0, 1, 2, 3, 4, 5, 6],
            "artifacts": [
                {"stack_id": 0, "resource_id": "platform-pki", "strategy": "archive", "sensitive": True, "restore_phase": "pre-prepare", "relative_path": "artifacts/stack0/platform-pki.tar", "sha256": "b" * 64, "size_bytes": 1},
                {"stack_id": 3, "resource_id": "litellm-database", "strategy": "postgres-custom-dump", "sensitive": True, "restore_phase": "post-prepare-pre-deploy", "relative_path": "artifacts/stack3/litellm-database.dump", "sha256": "c" * 64, "size_bytes": 1},
                {"stack_id": 4, "resource_id": "gitea-state", "strategy": "gitea-native-dump", "sensitive": True, "restore_phase": "post-prepare-pre-deploy", "relative_path": "artifacts/stack4/gitea-state.zip", "sha256": "d" * 64, "size_bytes": 1},
            ],
            "global_artifacts": [
                {"resource_id": "operational-env", "strategy": "file-copy", "sensitive": True, "restore_phase": "pre-prepare", "relative_path": "artifacts/global/operational.env", "sha256": "e" * 64, "size_bytes": 1}
            ],
            "prerequisites": [
                {"stack_id": 3, "resource_id": "litellm-salt", "kind": "REQUIRE", "strategy": "external-config", "sensitive": True},
                {"stack_id": 6, "resource_id": "hermes-knowledge", "kind": "EXTERNAL", "strategy": "git", "sensitive": False},
            ],
        }

    def test_completed_metadata_accepts_declared_global_artifacts(self):
        dr_archive.validate_completed_metadata(self.metadata())

    def test_completed_metadata_rejects_unknown_top_level_field(self):
        data = self.metadata()
        data["surprise"] = True
        with self.assertRaises(dr_archive.ArchiveBackupError):
            dr_archive.validate_completed_metadata(data)

    def test_postgres_locator_selects_stack3_from_full_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = self.metadata()
            artifact = root / "artifacts/stack3/litellm-database.dump"
            artifact.parent.mkdir(parents=True)
            artifact.write_bytes(b"x")
            data["artifacts"][1]["sha256"] = dr_archive.sha256_file(artifact)
            (root / "backup.json").write_text(json.dumps(data), encoding="utf-8")
            meta, selected = dr_postgres_artifact_verify.locate_artifact(root)
            self.assertEqual(meta["stack_id"], 3)
            self.assertEqual(selected, artifact)

    def test_stack4_metadata_accepts_full_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = self.metadata()
            (root / "backup.json").write_text(json.dumps(data), encoding="utf-8")
            loaded = dr_stack4_inspect.read_metadata(root)
            self.assertEqual(loaded["requested"], ["all"])


if __name__ == "__main__":
    unittest.main()
