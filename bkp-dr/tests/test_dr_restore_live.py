from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import dr_archive
import dr_restore_compat
import dr_restore_live


class RestoreLiveTests(unittest.TestCase):
    def test_require_clean_target_accepts_absent_paths_and_absent_docker_objects(self) -> None:
        manifests = {
            0: {"owns": ["docker-network:redlocal", "container:foundation"]},
            5: {"owns": ["container:dockhand", "volume:dockhand_data"]},
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stacks = root / "stacks"
            runtime = root / "runtime"
            absent = mock.Mock(returncode=1)
            with mock.patch.object(dr_restore_live, "_run", return_value=absent):
                dr_restore_live.require_clean_target(stacks, runtime, manifests, [0, 5])

    def test_require_clean_target_rejects_nonempty_stacks_root(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stacks = root / "stacks"
            runtime = root / "runtime"
            stacks.mkdir()
            (stacks / "leftover").write_text("x", encoding="utf-8")
            with self.assertRaises(dr_restore_live.RestoreLiveError):
                dr_restore_live.require_clean_target(stacks, runtime, {0: {"owns": []}}, [0])

    def test_require_clean_target_rejects_existing_owned_volume(self) -> None:
        manifests = {5: {"owns": ["volume:dockhand_data"]}}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stacks = root / "stacks"
            runtime = root / "runtime"
            exists = mock.Mock(returncode=0)
            with mock.patch.object(dr_restore_live, "_run", return_value=exists):
                with self.assertRaisesRegex(dr_restore_live.RestoreLiveError, "volume"):
                    dr_restore_live.require_clean_target(stacks, runtime, manifests, [5])

    def test_install_always_requires_yes(self) -> None:
        ok = mock.Mock(returncode=0, stdout=b"", stderr=b"")
        with mock.patch.object(dr_restore_compat, "_run", return_value=ok) as run:
            dr_restore_live._install(Path("/tmp/target"), [0, 1, 2], reconcile=True, label="test")
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[:5], ["python3", "install.py", "0", "1", "2"])
        self.assertIn("--reconcile", cmd)
        self.assertEqual(cmd[-1], "--yes")

    def test_execute_refuses_without_explicit_confirmation(self) -> None:
        with self.assertRaisesRegex(dr_restore_live.RestoreLiveError, "confirmation"):
            dr_restore_live.execute_restore_all(Path("/tmp/backup"), confirm_clean_target=False)

    def test_read_env_artifact_accepts_canonical_resource_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env = root / "operational.env"
            env.write_text("STACKS_ROOT=/tmp/stacks\nBASE_PATH=/tmp/runtime\n", encoding="utf-8")
            metadata = {"global_artifacts": [{"resource_id": "operational-env", "relative_path": "operational.env"}]}
            path, values = dr_restore_live._read_env_artifact(root, metadata)
            self.assertEqual(path, env)
            self.assertEqual(values["STACKS_ROOT"], "/tmp/stacks")

    def test_managed_archive_replaces_prepared_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base = root / "runtime"
            source = root / "source" / "data"
            source.mkdir(parents=True)
            (source / "webui.db").write_text("state", encoding="utf-8")
            archive = root / "open-webui-data.tar"
            dr_archive.create_tar_archive(source, archive)

            target = base / "service_-_open-webui" / "data"
            target.mkdir(parents=True)
            backup_set = root / "backup"
            backup_set.mkdir()
            backup_archive = backup_set / "artifact.tar"
            backup_archive.write_bytes(archive.read_bytes())

            artifact = {"relative_path": "artifact.tar"}
            resource = {"config": {"source": {"path": "${BASE_PATH}/service_-_open-webui/data"}}}
            dr_restore_live._restore_managed_archive(backup_set, artifact, resource, base)
            self.assertEqual((target / "webui.db").read_text(encoding="utf-8"), "state")

    def test_managed_archive_rejects_nonempty_prepared_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "runtime"
            target = base / "service_-_open-webui" / "data"
            target.mkdir(parents=True)
            (target / "unexpected").write_text("x", encoding="utf-8")
            resource = {"config": {"source": {"path": "${BASE_PATH}/service_-_open-webui/data"}}}
            with self.assertRaisesRegex(dr_restore_live.RestoreLiveError, "empty"):
                dr_restore_live._restore_managed_archive(Path(td), {"relative_path": "missing.tar"}, resource, base)


if __name__ == "__main__":
    unittest.main()
