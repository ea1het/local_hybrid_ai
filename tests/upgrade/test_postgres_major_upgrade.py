#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Contract tests for the isolated PostgreSQL major-version upgrade path.

These tests never touch a real PostgreSQL server or Docker daemon: every
docker/pg_dump/pg_restore call is mocked. Only filesystem effects (the data
directory move, the .env rewrite, the staging directory) run for real
against a temporary directory tree.
"""

from __future__ import annotations
import subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock
from local_ai_cli.common import postgres as pg
from local_ai_cli.upgrade import _postgres_major_upgrade as pgu
from local_ai_cli.upgrade.engine import UpgradeExecutionError


class PostgresMajorUpgradeTests(unittest.TestCase):
    def _apply(self):
        return {
            "type": pgu.TYPE,
            "image_env_key": "LITELLM_POSTGRES_IMAGE",
            "database_env": "LITELLM_DB_NAME",
            "role_env": "LITELLM_DB_USER",
            "data_path_env": "BASE_PATH",
            "data_relative_path": "service_-_litellm-postgres/data",
            "dependent_containers": ["litellm"],
            "deploy": ["./02-postgres.sh"],
        }

    def _fixture(self, tmp):
        root = Path(tmp) / "project"
        (root / "stack3_-_litellm").mkdir(parents=True)
        runtime_root = Path(tmp) / "runtime"
        base_path = Path(tmp) / "base"
        data_dir = base_path / "service_-_litellm-postgres" / "data"
        data_dir.mkdir(parents=True)
        env_path = root / ".env"
        env_path.write_text("LITELLM_POSTGRES_IMAGE=postgres:17.10-alpine\n")
        env_values = {"LITELLM_DB_NAME": "litellm", "LITELLM_DB_USER": "litellm", "BASE_PATH": str(base_path)}
        return root, runtime_root, data_dir, env_path, env_values

    def _run_execute(self, root, runtime_root, env_path, env_values, *, calls):
        def fake_run(cmd, *, cwd=None, capture=True):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        def fake_dump(cmd, destination):
            destination.write_bytes(b"fake-custom-dump")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with (
            mock.patch.object(pgu, "_run", side_effect=fake_run),
            mock.patch.object(pgu, "_container_state", return_value="running/healthy"),
            mock.patch.object(pgu, "_wait_healthy"),
            mock.patch.object(pg, "list_user_tables", side_effect=[["public.a"], ["public.a"]]),
            mock.patch.object(pg, "run_binary_to_file", side_effect=fake_dump),
            mock.patch.object(
                pg, "run_binary_stdin", return_value=subprocess.CompletedProcess([], 0, "", "")
            ) as restore,
        ):
            pgu.execute(
                root=root,
                runtime_root=runtime_root,
                stack_directory="stack3_-_litellm",
                component_key="stack3/postgresql",
                apply=self._apply(),
                container="litellm-postgres",
                target_image_ref="postgres:18.0-alpine",
                env_path=env_path,
                env_values=env_values,
                quiet=True,
            )
        return restore

    def test_happy_path_dumps_stops_moves_restores_and_restarts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, runtime_root, data_dir, env_path, env_values = self._fixture(tmp)
            calls = []
            restore = self._run_execute(root, runtime_root, env_path, env_values, calls=calls)
            self.assertFalse(data_dir.exists())
            aside = list(data_dir.parent.glob("data.pre-upgrade-*"))
            self.assertEqual(len(aside), 1)
            self.assertEqual(env_path.read_text(), "LITELLM_POSTGRES_IMAGE=postgres:18.0-alpine\n")
            restore.assert_called_once()
            self.assertIn(["docker", "stop", "litellm"], calls)
            self.assertIn(["docker", "stop", "litellm-postgres"], calls)
            self.assertIn(["docker", "start", "litellm"], calls)
            deploy_calls = [c for c in calls if c[:2] == ["bash", "./02-postgres.sh"]]
            self.assertEqual(len(deploy_calls), 1)
            work_root = runtime_root / "platform" / "postgres-major-upgrade"
            self.assertEqual(list(work_root.iterdir()), [])

    def test_empty_dump_aborts_before_any_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, runtime_root, data_dir, env_path, env_values = self._fixture(tmp)
            calls = []

            def fake_run(cmd, *, cwd=None, capture=True):
                calls.append(cmd)
                return subprocess.CompletedProcess(cmd, 0, "", "")

            def empty_dump(cmd, destination):
                destination.write_bytes(b"")
                return subprocess.CompletedProcess(cmd, 0, "", "")

            with (
                mock.patch.object(pgu, "_run", side_effect=fake_run),
                mock.patch.object(pgu, "_container_state", return_value="running/healthy"),
                mock.patch.object(pg, "list_user_tables", return_value=["public.a"]),
                mock.patch.object(pg, "run_binary_to_file", side_effect=empty_dump),
            ):
                with self.assertRaises(UpgradeExecutionError) as ctx:
                    pgu.execute(
                        root=root,
                        runtime_root=runtime_root,
                        stack_directory="stack3_-_litellm",
                        component_key="stack3/postgresql",
                        apply=self._apply(),
                        container="litellm-postgres",
                        target_image_ref="postgres:18.0-alpine",
                        env_path=env_path,
                        env_values=env_values,
                        quiet=True,
                    )
            self.assertEqual(ctx.exception.code, "UPGRADE_BACKUP_INVALID")
            self.assertTrue(data_dir.is_dir())
            self.assertEqual(calls, [])
            self.assertEqual(env_path.read_text(), "LITELLM_POSTGRES_IMAGE=postgres:17.10-alpine\n")

    def test_restored_table_mismatch_blocks_dependent_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, runtime_root, data_dir, env_path, env_values = self._fixture(tmp)
            calls = []

            def fake_run(cmd, *, cwd=None, capture=True):
                calls.append(cmd)
                return subprocess.CompletedProcess(cmd, 0, "", "")

            def fake_dump(cmd, destination):
                destination.write_bytes(b"fake-custom-dump")
                return subprocess.CompletedProcess(cmd, 0, "", "")

            with (
                mock.patch.object(pgu, "_run", side_effect=fake_run),
                mock.patch.object(pgu, "_container_state", return_value="running/healthy"),
                mock.patch.object(pgu, "_wait_healthy"),
                mock.patch.object(pg, "list_user_tables", side_effect=[["public.a", "public.b"], ["public.a"]]),
                mock.patch.object(pg, "run_binary_to_file", side_effect=fake_dump),
                mock.patch.object(pg, "run_binary_stdin", return_value=subprocess.CompletedProcess([], 0, "", "")),
            ):
                with self.assertRaises(UpgradeExecutionError) as ctx:
                    pgu.execute(
                        root=root,
                        runtime_root=runtime_root,
                        stack_directory="stack3_-_litellm",
                        component_key="stack3/postgresql",
                        apply=self._apply(),
                        container="litellm-postgres",
                        target_image_ref="postgres:18.0-alpine",
                        env_path=env_path,
                        env_values=env_values,
                        quiet=True,
                    )
            self.assertEqual(ctx.exception.code, "UPGRADE_TARGET_NOT_RUNNING")
            self.assertNotIn(["docker", "start", "litellm"], calls)
            self.assertFalse(data_dir.exists())
            aside = list(data_dir.parent.glob("data.pre-upgrade-*"))
            self.assertEqual(len(aside), 1, "old data directory must be preserved for manual recovery")

    def test_source_not_running_is_rejected_before_any_dump(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, runtime_root, data_dir, env_path, env_values = self._fixture(tmp)
            with (
                mock.patch.object(pgu, "_container_state", return_value="exited"),
                mock.patch.object(pg, "list_user_tables") as list_tables,
            ):
                with self.assertRaises(UpgradeExecutionError) as ctx:
                    pgu.execute(
                        root=root,
                        runtime_root=runtime_root,
                        stack_directory="stack3_-_litellm",
                        component_key="stack3/postgresql",
                        apply=self._apply(),
                        container="litellm-postgres",
                        target_image_ref="postgres:18.0-alpine",
                        env_path=env_path,
                        env_values=env_values,
                        quiet=True,
                    )
            self.assertEqual(ctx.exception.code, "UPGRADE_TARGET_NOT_RUNNING")
            list_tables.assert_not_called()

    def test_incomplete_recipe_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, runtime_root, data_dir, env_path, env_values = self._fixture(tmp)
            apply = self._apply()
            del apply["role_env"]
            with self.assertRaises(UpgradeExecutionError) as ctx:
                pgu.execute(
                    root=root,
                    runtime_root=runtime_root,
                    stack_directory="stack3_-_litellm",
                    component_key="stack3/postgresql",
                    apply=apply,
                    container="litellm-postgres",
                    target_image_ref="postgres:18.0-alpine",
                    env_path=env_path,
                    env_values=env_values,
                    quiet=True,
                )
            self.assertEqual(ctx.exception.code, "UPGRADE_INTERNAL_CONFIG")


if __name__ == "__main__":
    unittest.main()
