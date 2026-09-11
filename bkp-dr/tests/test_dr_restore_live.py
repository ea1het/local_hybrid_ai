from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
        with mock.patch.object(dr_restore_live, "_run", return_value=ok) as run:
            dr_restore_live._install(Path("/tmp/target"), [0, 1, 2], reconcile=True, label="test")
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[:5], ["python3", "install.py", "0", "1", "2"])
        self.assertIn("--reconcile", cmd)
        self.assertEqual(cmd[-1], "--yes")

    def test_execute_refuses_without_explicit_confirmation(self) -> None:
        with self.assertRaisesRegex(dr_restore_live.RestoreLiveError, "confirmation"):
            dr_restore_live.execute_restore_all(Path("/tmp/backup"), confirm_clean_target=False)


if __name__ == "__main__":
    unittest.main()
