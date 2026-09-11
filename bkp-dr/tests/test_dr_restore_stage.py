import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import dr_restore_stage


class RestoreStageTests(unittest.TestCase):
    def test_destination_must_be_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "stage"
            root.mkdir()
            (root / "existing").write_text("x", encoding="utf-8")
            with self.assertRaises(dr_restore_stage.RestoreStageError):
                dr_restore_stage._ensure_private_empty_destination(root)

    def test_private_copy_uses_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            destination = root / "dest"
            source.write_text("SECRET=value\n", encoding="utf-8")
            dr_restore_stage._copy_private(source, destination)
            self.assertEqual(destination.read_bytes(), source.read_bytes())
            self.assertEqual(oct(destination.stat().st_mode & 0o777), "0o600")

    def test_safe_tar_rejects_traversal(self):
        with self.assertRaises(dr_restore_stage.RestoreStageError):
            dr_restore_stage._safe_tar_member("../escape")
        with self.assertRaises(dr_restore_stage.RestoreStageError):
            dr_restore_stage._safe_tar_member("/absolute")

    def test_extract_archive_expected_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src"
            (source / "pki").mkdir(parents=True)
            (source / "pki" / "cert.pem").write_text("cert", encoding="utf-8")
            archive = root / "pki.tar"
            with tarfile.open(archive, "w") as tf:
                tf.add(source / "pki", arcname="pki")
            destination = root / "restore"
            count = dr_restore_stage._extract_tar_safely(archive, destination, expected_root="pki")
            self.assertGreater(count, 0)
            self.assertEqual((destination / "pki" / "cert.pem").read_text(encoding="utf-8"), "cert")

    @mock.patch("dr_restore_stage.dr.load_manifests")
    @mock.patch("dr_restore_stage.dr_restore_all.read_completed_backup_set")
    @mock.patch("dr_restore_stage.dr_restore_all.plan_restore_all")
    @mock.patch("dr_restore_stage._materialize_source")
    def test_stage_restores_env_requirement_and_pki(self, materialize, plan_restore, read_metadata, load_manifests):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup = root / "backup"
            (backup / "artifacts" / "global").mkdir(parents=True)
            (backup / "artifacts" / "stack0").mkdir(parents=True)
            (backup / "artifacts" / "global" / "operational.env").write_text(
                "LITELLM_SALT_KEY=test-salt\n", encoding="utf-8"
            )
            pki_source = root / "pki-src"
            (pki_source / "pki").mkdir(parents=True)
            (pki_source / "pki" / "ca.crt").write_text("ca", encoding="utf-8")
            with tarfile.open(backup / "artifacts" / "stack0" / "platform-pki.tar", "w") as tf:
                tf.add(pki_source / "pki", arcname="pki")

            plan_restore.return_value = mock.Mock(source_commit="a" * 40, resolved_stacks=(0, 3))
            read_metadata.return_value = {
                "global_artifacts": [{"relative_path": "artifacts/global/operational.env"}],
                "artifacts": [{
                    "stack_id": 0,
                    "resource_id": "platform-pki",
                    "strategy": "archive",
                    "restore_phase": "pre-prepare",
                    "relative_path": "artifacts/stack0/platform-pki.tar",
                }],
                "prerequisites": [{
                    "stack_id": 3,
                    "resource_id": "litellm-salt",
                    "kind": "REQUIRE",
                    "strategy": "external-config",
                }],
            }
            load_manifests.return_value = {
                0: {"recovery": {"resources": []}},
                3: {"recovery": {"resources": [{
                    "id": "litellm-salt",
                    "config": {"source": {"key": "LITELLM_SALT_KEY"}},
                }]}},
            }

            def create_source(commit, destination):
                destination.mkdir(mode=0o700)
                (destination / "README.md").write_text("source", encoding="utf-8")
            materialize.side_effect = create_source

            destination = root / "stage"
            result = dr_restore_stage.stage_restore_all(backup, destination)
            self.assertTrue(result.env_restored)
            self.assertEqual(result.external_config_verified, 1)
            self.assertEqual(result.archives_restored, 1)
            self.assertTrue((destination / "runtime" / "service_-_platform" / "pki" / "ca.crt").is_file())
            self.assertEqual(oct((destination / "source" / ".env").stat().st_mode & 0o777), "0o600")


if __name__ == "__main__":
    unittest.main()
