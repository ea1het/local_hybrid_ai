import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import dr_restore_drill


class RestoreDrillTests(unittest.TestCase):
    @mock.patch("dr_restore_drill._verify_external_prerequisites", return_value=1)
    @mock.patch("dr_restore_drill.dr_restore_managed.run_managed_restore")
    @mock.patch("dr_restore_drill.dr_restore_stage.stage_restore_all")
    @mock.patch("dr_restore_drill.dr_restore_all.plan_restore_all")
    def test_orchestrates_stage_managed_external_in_order(self, plan, stage, managed, external):
        plan.return_value = SimpleNamespace(source_commit="a" * 40, checksums_verified=5)
        stage.return_value = SimpleNamespace(
            source_root=Path("/isolated/source"),
            env_restored=True,
            archives_restored=1,
        )
        managed.return_value = SimpleNamespace(
            postgres_tables=75,
            postgres_nonempty_tables=25,
            gitea_tables=116,
            gitea_nonempty_tables=38,
            gitea_repositories=8,
            gitea_health=True,
        )
        result = dr_restore_drill.run_restore_drill(Path("/backup"), Path("/isolated"))
        self.assertEqual(result.postgres_tables, 75)
        self.assertEqual(result.gitea_tables, 116)
        self.assertEqual(result.external_git_verified, 1)
        self.assertTrue(result.gitea_health)
        stage.assert_called_once_with(Path("/backup"), Path("/isolated"))
        managed.assert_called_once_with(Path("/backup"), Path("/isolated"))
        external.assert_called_once_with(Path("/backup"), Path("/isolated/source/.env"))

    @mock.patch("dr_restore_drill.dr_stack6_verify.verify_stack6_memory")
    @mock.patch("dr_restore_drill.dr_restore_all.read_completed_backup_set")
    def test_external_git_verification_is_strategy_driven(self, read_meta, verify):
        read_meta.return_value = {
            "prerequisites": [
                {"stack_id": 6, "resource_id": "hermes-knowledge", "kind": "EXTERNAL", "strategy": "git"}
            ]
        }
        count = dr_restore_drill._verify_external_prerequisites(Path("/backup"), Path("/stage/.env"))
        self.assertEqual(count, 1)
        verify.assert_called_once_with(Path("/stage/.env"))

    @mock.patch("dr_restore_drill.dr_restore_all.read_completed_backup_set")
    def test_unknown_external_strategy_fails_closed(self, read_meta):
        read_meta.return_value = {
            "prerequisites": [
                {"stack_id": 9, "resource_id": "x", "kind": "EXTERNAL", "strategy": "unknown"}
            ]
        }
        with self.assertRaises(dr_restore_drill.RestoreDrillError):
            dr_restore_drill._verify_external_prerequisites(Path("/backup"), Path("/stage/.env"))


if __name__ == "__main__":
    unittest.main()
