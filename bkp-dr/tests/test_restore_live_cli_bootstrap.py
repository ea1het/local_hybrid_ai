from __future__ import annotations

import importlib.util
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock


CLI_PATH = Path(__file__).resolve().parents[1] / "restore-live.py"
SPEC = importlib.util.spec_from_file_location("restore_live_cli", CLI_PATH)
assert SPEC is not None and SPEC.loader is not None
restore_live_cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(restore_live_cli)


class RestoreLiveBootstrapTests(unittest.TestCase):
    def _bootstrap(self, root: Path) -> Path:
        source = root / "bootstrap"
        source.mkdir()
        for name in ("ssh_config", "id_ed25519", "known_hosts"):
            (source / name).write_text(f"{name}\n", encoding="utf-8")
        return source

    def test_validate_rejects_missing_required_material(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "bootstrap"
            source.mkdir()
            (source / "id_ed25519").write_text("key\n", encoding="utf-8")
            with self.assertRaises(restore_live_cli.BootstrapError):
                restore_live_cli._validate_memory_sync_bootstrap(source)

    def test_install_bootstrap_copies_private_material_to_clean_runtime_target(self) -> None:
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
            with mock.patch.object(restore_live_cli.dr_restore_all, "read_completed_backup_set", return_value={}), \
                 mock.patch.object(restore_live_cli.dr_restore_live, "_read_env_artifact", return_value=(root / "env", values)), \
                 mock.patch.object(restore_live_cli.dr_restore_live, "_absolute_safe_path", return_value=base), \
                 mock.patch.object(restore_live_cli.os, "chown"):
                target = restore_live_cli._install_memory_sync_bootstrap(root / "backup", source)

            self.assertEqual(target, base / "service_-_hermes-memory-sync" / "ssh")
            for name in ("ssh_config", "id_ed25519", "known_hosts"):
                path = target / name
                self.assertTrue(path.is_file())
                self.assertEqual(path.read_text(encoding="utf-8"), f"{name}\n")
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o700)

    def test_install_bootstrap_refuses_nonempty_target(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self._bootstrap(root)
            base = root / "runtime"
            target = base / "service_-_hermes-memory-sync" / "ssh"
            target.mkdir(parents=True)
            (target / "unexpected").write_text("x", encoding="utf-8")
            values = {
                "BASE_PATH": str(base),
                "MEMORY_SYNC_SERVICE": "service_-_hermes-memory-sync",
                "HERMES_UID": "1000",
                "HERMES_GID": "1000",
            }
            with mock.patch.object(restore_live_cli.dr_restore_all, "read_completed_backup_set", return_value={}), \
                 mock.patch.object(restore_live_cli.dr_restore_live, "_read_env_artifact", return_value=(root / "env", values)), \
                 mock.patch.object(restore_live_cli.dr_restore_live, "_absolute_safe_path", return_value=base):
                with self.assertRaises(restore_live_cli.BootstrapError):
                    restore_live_cli._install_memory_sync_bootstrap(root / "backup", source)

    def test_enable_memory_sync_starts_profile_and_requires_running_container(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stacks = root / "stacks"
            (stacks / "stack6_-_hermes").mkdir(parents=True)
            values = {"MEMORY_SYNC_CONTAINER": "hermes-memory-sync"}
            compose_ok = mock.Mock(returncode=0, stdout="", stderr="")
            inspect_ok = mock.Mock(returncode=0, stdout="true\n", stderr="")
            with mock.patch.object(restore_live_cli.dr_restore_all, "read_completed_backup_set", return_value={}), \
                 mock.patch.object(restore_live_cli.dr_restore_live, "_read_env_artifact", return_value=(root / "env", values)), \
                 mock.patch.object(restore_live_cli.subprocess, "run", side_effect=[compose_ok, inspect_ok]) as run:
                restore_live_cli._enable_memory_sync(root / "backup", {"stacks_root": str(stacks)})

            compose_cmd = run.call_args_list[0].args[0]
            self.assertEqual(compose_cmd[:4], ["docker", "compose", "--profile", "git-memory"])
            self.assertIn("hermes-memory-sync", compose_cmd)
            self.assertEqual(run.call_args_list[0].kwargs["cwd"], stacks / "stack6_-_hermes")
            inspect_cmd = run.call_args_list[1].args[0]
            self.assertEqual(inspect_cmd[-1], "hermes-memory-sync")


if __name__ == "__main__":
    unittest.main()
