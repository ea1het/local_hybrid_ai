import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import dr_restore_managed


class RestoreManagedTests(unittest.TestCase):
    def test_container_prefixes_are_dr_specific(self):
        self.assertTrue(dr_restore_managed.POSTGRES_PREFIX.startswith("local-hybrid-ai-dr-"))
        self.assertTrue(dr_restore_managed.GITEA_PREFIX.startswith("local-hybrid-ai-dr-"))
        self.assertNotEqual(dr_restore_managed.POSTGRES_PREFIX, "litellm-postgres")
        self.assertNotEqual(dr_restore_managed.GITEA_PREFIX, "gitea")

    def test_stage_overlapping_live_base_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stage = root / "live" / "child"
            (stage / "source").mkdir(parents=True)
            (stage / "runtime").mkdir()
            (stage / "source" / ".env").write_text(f"BASE_PATH={root / 'live'}\n", encoding="utf-8")
            with self.assertRaises(dr_restore_managed.RestoreManagedError):
                dr_restore_managed._require_stage(stage)

    def test_postgres_image_is_read_from_staged_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            compose = source / "stack3_-_litellm" / "docker-compose.yml"
            compose.parent.mkdir(parents=True)
            compose.write_text("services:\n  db:\n    image: postgres:17.10-alpine@sha256:abc\n", encoding="utf-8")
            self.assertEqual(dr_restore_managed._postgres_image(source), "postgres:17.10-alpine@sha256:abc")

    def test_artifact_selection_rejects_ambiguity(self):
        metadata = {"artifacts": [
            {"strategy": "postgres-custom-dump", "resource_id": "litellm-database"},
            {"strategy": "postgres-custom-dump", "resource_id": "litellm-database"},
        ]}
        with self.assertRaises(dr_restore_managed.RestoreManagedError):
            dr_restore_managed._artifact(metadata, strategy="postgres-custom-dump", resource_id="litellm-database")

    @mock.patch("dr_restore_managed._run")
    def test_remove_container_targets_only_supplied_name(self, run):
        run.side_effect = [mock.Mock(returncode=0), mock.Mock(returncode=0)]
        dr_restore_managed._remove_container("local-hybrid-ai-dr-gitea-test")
        self.assertEqual(run.call_args_list[-1].args[0], ["docker", "rm", "-f", "local-hybrid-ai-dr-gitea-test"])


if __name__ == "__main__":
    unittest.main()
