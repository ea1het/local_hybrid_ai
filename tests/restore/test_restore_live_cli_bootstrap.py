#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Protect Stack6 SSH bootstrap handling in the importable restore service."""

from __future__ import annotations
import stat, tempfile, unittest
from pathlib import Path
from unittest import mock
from local_ai_cli.restore import _restore_live_service as restore_service


class RestoreLiveBootstrapTests(unittest.TestCase):
    def _bootstrap(self, root: Path) -> Path:
        source = root / "bootstrap"
        source.mkdir()
        for name in ("ssh_config", "id_ed25519", "known_hosts"):
            (source / name).write_text(f"{name}\n", encoding="utf-8")
        return source

    def test_global_operational_env_uses_resource_id_contract(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env = root / "artifacts" / "global" / "operational.env"
            env.parent.mkdir(parents=True)
            env.write_text("STACKS_ROOT=/opt/docker/stacks\nBASE_PATH=/opt/docker/runtime\n")
            metadata = {
                "global_artifacts": [
                    {"resource_id": "operational-env", "relative_path": "artifacts/global/operational.env"}
                ]
            }
            path, values = restore_service.read_env_artifact(root, metadata)
            self.assertEqual(path, env)
            self.assertEqual(values["STACKS_ROOT"], "/opt/docker/stacks")

    def test_global_operational_env_rejects_wrong_field_name(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env = root / "artifacts" / "global" / "operational.env"
            env.parent.mkdir(parents=True)
            env.write_text("STACKS_ROOT=/opt/docker/stacks\n")
            metadata = {
                "global_artifacts": [{"id": "operational-env", "relative_path": "artifacts/global/operational.env"}]
            }
            with self.assertRaises(restore_service.restore_live.RestoreLiveError):
                restore_service.read_env_artifact(root, metadata)

    def test_validate_rejects_missing_required_material(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "bootstrap"
            source.mkdir()
            (source / "id_ed25519").write_text("key\n")
            with self.assertRaises(restore_service.BootstrapError):
                restore_service.validate_memory_sync_bootstrap(source)

    def test_install_bootstrap_copies_private_material_to_clean_runtime_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self._bootstrap(root)
            base = root / "runtime"
            values = {
                "BASE_PATH": str(base),
                "MEMORY_SYNC_SERVICE": "service_-_hermes-memory-sync",
                "HERMES_UID": "1000",
                "HERMES_GID": "1000",
            }
            with (
                mock.patch.object(restore_service.restore_all, "read_completed_backup_set", return_value={}),
                mock.patch.object(restore_service, "read_env_artifact", return_value=(root / "env", values)),
                mock.patch.object(restore_service.restore_live, "_absolute_safe_path", return_value=base),
                mock.patch.object(restore_service.os, "chown"),
            ):
                target = restore_service.install_memory_sync_bootstrap(root / "backup", source)
            self.assertEqual(target, base / "service_-_hermes-memory-sync" / "ssh")
            for name in ("ssh_config", "id_ed25519", "known_hosts"):
                path = target / name
                self.assertTrue(path.is_file())
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_install_bootstrap_refuses_nonempty_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self._bootstrap(root)
            base = root / "runtime"
            target = base / "service_-_hermes-memory-sync" / "ssh"
            target.mkdir(parents=True)
            (target / "unexpected").write_text("x")
            values = {
                "BASE_PATH": str(base),
                "MEMORY_SYNC_SERVICE": "service_-_hermes-memory-sync",
                "HERMES_UID": "1000",
                "HERMES_GID": "1000",
            }
            with (
                mock.patch.object(restore_service.restore_all, "read_completed_backup_set", return_value={}),
                mock.patch.object(restore_service, "read_env_artifact", return_value=(root / "env", values)),
                mock.patch.object(restore_service.restore_live, "_absolute_safe_path", return_value=base),
            ):
                with self.assertRaises(restore_service.BootstrapError):
                    restore_service.install_memory_sync_bootstrap(root / "backup", source)

    def test_enable_memory_sync_starts_profile_and_requires_running_container(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stacks = root / "stacks"
            (stacks / "stack6_-_hermes").mkdir(parents=True)
            values = {"MEMORY_SYNC_CONTAINER": "hermes-memory-sync"}
            compose_ok = mock.Mock(returncode=0, stdout="", stderr="")
            inspect_ok = mock.Mock(returncode=0, stdout="true\n", stderr="")
            with (
                mock.patch.object(restore_service.restore_all, "read_completed_backup_set", return_value={}),
                mock.patch.object(restore_service, "read_env_artifact", return_value=(root / "env", values)),
                mock.patch.object(restore_service.restore_compat, "wait_required_runtime") as wait_ready,
                mock.patch.object(restore_service.subprocess, "run", side_effect=[compose_ok, inspect_ok]) as run,
            ):
                restore_service.enable_memory_sync(root / "backup", {"stacks_root": str(stacks)})
            wait_ready.assert_called_once_with(stacks, [6], timeout=240)
            self.assertIn("hermes-memory-sync", run.call_args_list[0].args[0])


if __name__ == "__main__":
    unittest.main()
