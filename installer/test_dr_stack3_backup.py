import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import dr_stack3_backup
import dr_stack3_restore_verify


class Stack3BackupAdapterTests(unittest.TestCase):
    def test_expected_dependency_complete_artifact_paths(self):
        self.assertEqual(
            dr_stack3_backup.PKI_RELATIVE_PATH,
            "artifacts/stack0/platform-pki.tar",
        )
        self.assertEqual(
            dr_stack3_backup.DB_RELATIVE_PATH,
            "artifacts/stack3/litellm-database.dump",
        )

    def test_select_resources_requires_stack0_and_stack3_plan(self):
        manifests = {
            0: {
                "recovery": {
                    "resources": [
                        {
                            "id": "platform-pki",
                            "strategy": "archive",
                            "sensitive": True,
                            "config": {"source": {"path": "${BASE_PATH}/pki"}},
                        }
                    ]
                }
            },
            3: {
                "recovery": {
                    "resources": [
                        {
                            "id": "litellm-database",
                            "strategy": "postgres-custom-dump",
                            "sensitive": True,
                            "config": {"source": {"database_env": "LITELLM_DB_NAME"}},
                        },
                        {
                            "id": "litellm-salt",
                            "strategy": "external-config",
                            "sensitive": True,
                            "config": {"source": {"key": "LITELLM_SALT_KEY"}},
                        },
                    ]
                }
            },
        }
        pki, database, salt = dr_stack3_backup.select_resources(manifests, [0, 3])
        self.assertEqual(pki["id"], "platform-pki")
        self.assertEqual(database["id"], "litellm-database")
        self.assertEqual(salt["id"], "litellm-salt")
        with self.assertRaises(dr_stack3_backup.Stack3BackupError):
            dr_stack3_backup.select_resources(manifests, [3])

    def test_restore_checksum_verifier_accepts_exact_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "artifacts/stack3").mkdir(parents=True)
            artifact = root / "artifacts/stack3/litellm-database.dump"
            artifact.write_bytes(b"test-custom-dump")
            artifact_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
            metadata = {
                "schema_version": 1,
                "kind": "local-hybrid-ai-backup-set",
                "created_at": "2026-09-10T20:00:00Z",
                "source_commit": "a" * 40,
                "requested": ["3"],
                "resolved_stacks": [0, 3],
                "artifacts": [
                    {
                        "stack_id": 3,
                        "resource_id": "litellm-database",
                        "strategy": "postgres-custom-dump",
                        "sensitive": True,
                        "restore_phase": "post-prepare-pre-deploy",
                        "relative_path": "artifacts/stack3/litellm-database.dump",
                        "sha256": artifact_hash,
                        "size_bytes": artifact.stat().st_size,
                    }
                ],
                "prerequisites": [],
            }
            (root / "backup.json").write_text(json.dumps(metadata), encoding="utf-8")
            metadata_hash = hashlib.sha256((root / "backup.json").read_bytes()).hexdigest()
            (root / "checksums.sha256").write_text(
                f"{artifact_hash}  artifacts/stack3/litellm-database.dump\n"
                f"{metadata_hash}  backup.json\n",
                encoding="utf-8",
            )
            dr_stack3_restore_verify.verify_checksums(root, metadata)

    def test_restore_checksum_verifier_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "artifacts/stack3").mkdir(parents=True)
            artifact = root / "artifacts/stack3/litellm-database.dump"
            artifact.write_bytes(b"original")
            artifact_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
            metadata = {
                "artifacts": [
                    {
                        "relative_path": "artifacts/stack3/litellm-database.dump",
                        "sha256": artifact_hash,
                    }
                ]
            }
            (root / "backup.json").write_text("{}", encoding="utf-8")
            metadata_hash = hashlib.sha256((root / "backup.json").read_bytes()).hexdigest()
            (root / "checksums.sha256").write_text(
                f"{artifact_hash}  artifacts/stack3/litellm-database.dump\n"
                f"{metadata_hash}  backup.json\n",
                encoding="utf-8",
            )
            artifact.write_bytes(b"tampered")
            with self.assertRaises(dr_stack3_restore_verify.Stack3RestoreVerifyError):
                dr_stack3_restore_verify.verify_checksums(root, metadata)

    def test_database_artifact_selector_is_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "artifacts/stack3/litellm-database.dump"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"dump")
            metadata = {
                "artifacts": [
                    {
                        "stack_id": 3,
                        "resource_id": "litellm-database",
                        "strategy": "postgres-custom-dump",
                        "relative_path": "artifacts/stack3/litellm-database.dump",
                        "size_bytes": 4,
                    }
                ]
            }
            self.assertEqual(
                dr_stack3_restore_verify.select_database_artifact(root, metadata),
                path,
            )


if __name__ == "__main__":
    unittest.main()
