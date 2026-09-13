from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import dr_restore_compat


class RestoreCompatibilityTests(unittest.TestCase):
    def _target(self, root: Path) -> Path:
        stacks = root / "stacks"
        installer_dir = stacks / "installer"
        installer_dir.mkdir(parents=True)
        lifecycle = {
            "schema_version": 1,
            "stacks": {
                "6": {
                    "directory": "stack6_-_hermes",
                    "required_containers": ["hermes", "hermes-sandbox"],
                }
            },
        }
        (installer_dir / "lifecycle.json").write_text(json.dumps(lifecycle), encoding="utf-8")
        # The compatibility helper deliberately refuses to invoke an installer
        # path that is not actually present in the target source tree.  This
        # fixture models the current repository layout without executing it.
        (installer_dir / "install.py").write_text("# test installer placeholder\n", encoding="utf-8")
        return stacks

    def test_install_accepts_only_exact_transient_failure_after_independent_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            stacks = self._target(Path(td))
            failed = mock.Mock(returncode=1, stdout=b"", stderr=b"INSTALLER ERROR: required runtime validation failed: stack6:hermes=running/starting")
            with mock.patch.object(dr_restore_compat, "_run", return_value=failed) as run, \
                 mock.patch.object(dr_restore_compat, "wait_required_runtime") as wait:
                dr_restore_compat.install_with_readiness_compat(stacks, [6], label="stack6")
            self.assertEqual(run.call_args.args[0][:2], ["python3", "installer/install.py"])
            wait.assert_called_once_with(stacks, [6])

    def test_install_rejects_unrelated_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            stacks = self._target(Path(td))
            failed = mock.Mock(returncode=1, stdout=b"", stderr=b"some other failure")
            with mock.patch.object(dr_restore_compat, "_run", return_value=failed):
                with self.assertRaises(dr_restore_compat.RestoreCompatibilityError):
                    dr_restore_compat.install_with_readiness_compat(stacks, [6], label="stack6")

    def test_legacy_root_installer_remains_supported_for_historical_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stacks = self._target(root)
            (stacks / "installer" / "install.py").unlink()
            (stacks / "install.py").write_text("# historical installer placeholder\n", encoding="utf-8")
            ok = mock.Mock(returncode=0, stdout=b"", stderr=b"")
            with mock.patch.object(dr_restore_compat, "_run", return_value=ok) as run:
                dr_restore_compat.install_with_readiness_compat(stacks, [6], label="stack6")
            self.assertEqual(run.call_args.args[0][:2], ["python3", "install.py"])

    def test_wait_requires_health_when_healthcheck_exists(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            stacks = self._target(Path(td))
            states = {
                "hermes": [("running", "starting"), ("running", "healthy")],
                "hermes-sandbox": [("running", "healthy"), ("running", "healthy")],
            }

            def state(name: str):
                values = states[name]
                return values.pop(0) if len(values) > 1 else values[0]

            with mock.patch.object(dr_restore_compat, "_container_state", side_effect=state), \
                 mock.patch.object(dr_restore_compat.time, "sleep"):
                dr_restore_compat.wait_required_runtime(stacks, [6], timeout=5)


if __name__ == "__main__":
    unittest.main()
