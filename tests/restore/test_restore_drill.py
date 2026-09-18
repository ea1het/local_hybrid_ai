# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Protect orchestration of the isolated end-to-end disaster-recovery drill.

The drill must stage source/configuration, restore managed state and verify external
prerequisites without touching live runtime. These tests also ensure EXTERNAL
resources are dispatched by declared strategy and unknown strategies fail closed.
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2] / "src" / "local_ai_cli" / "restore"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import restore_drill


class RestoreDrillTests(unittest.TestCase):
    @mock.patch("restore_drill._verify_external_prerequisites", return_value=1)
    @mock.patch("restore_drill.restore_managed.run_managed_restore")
    @mock.patch("restore_drill.restore_stage.stage_restore_all")
    @mock.patch("restore_drill.restore_all.plan_restore_all")
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
        result = restore_drill.run_restore_drill(Path("/backup"), Path("/isolated"))
        self.assertEqual(result.postgres_tables, 75)
        self.assertEqual(result.gitea_tables, 116)
        self.assertEqual(result.external_git_verified, 1)
        self.assertTrue(result.gitea_health)
        stage.assert_called_once_with(Path("/backup"), Path("/isolated"))
        managed.assert_called_once_with(Path("/backup"), Path("/isolated"))
        external.assert_called_once_with(Path("/backup"), Path("/isolated/source/.env"))

    @mock.patch("restore_drill.stack6_verify.verify_stack6_memory")
    @mock.patch("restore_drill.restore_all.read_completed_backup_set")
    def test_external_git_verification_is_strategy_driven(self, read_meta, verify):
        read_meta.return_value = {
            "prerequisites": [
                {"stack_id": 6, "resource_id": "hermes-knowledge", "kind": "EXTERNAL", "strategy": "git"}
            ]
        }
        count = restore_drill._verify_external_prerequisites(Path("/backup"), Path("/stage/.env"))
        self.assertEqual(count, 1)
        verify.assert_called_once_with(Path("/stage/.env"))

    @mock.patch("restore_drill.restore_all.read_completed_backup_set")
    def test_unknown_external_strategy_fails_closed(self, read_meta):
        read_meta.return_value = {
            "prerequisites": [
                {"stack_id": 9, "resource_id": "x", "kind": "EXTERNAL", "strategy": "unknown"}
            ]
        }
        with self.assertRaises(restore_drill.RestoreDrillError):
            restore_drill._verify_external_prerequisites(Path("/backup"), Path("/stage/.env"))


if __name__ == "__main__":
    unittest.main()
