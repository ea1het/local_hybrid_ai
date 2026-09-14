# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Contract tests for the read-only ``./local-ai doctor`` diagnostics surface.

The tests keep diagnostic status, JSON shape and non-mutating prerequisite
checks stable without requiring a real Docker daemon or operational host.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from commands import doctor


class DoctorTests(unittest.TestCase):
    def test_payload_success_depends_only_on_fail_status(self):
        result = doctor.payload([
            {"id": "a", "status": "pass", "message": "ok", "details": {}},
            {"id": "b", "status": "warn", "message": "warning", "details": {}},
        ])
        self.assertEqual(result["schema_version"], "1")
        self.assertEqual(result["command"], "doctor")
        self.assertTrue(result["success"])

        failed = doctor.payload([
            {"id": "a", "status": "fail", "message": "bad", "details": {}},
        ])
        self.assertFalse(failed["success"])

    def test_run_checks_reports_required_prerequisites_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "local-ai").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            env = root / ".env"
            env.write_text("TEST=1\n", encoding="utf-8")
            env.chmod(0o600)
            runtime = root / "runtime"
            runtime.mkdir()

            compose = mock.Mock(returncode=0, stdout="Docker Compose version", stderr="")
            with mock.patch.object(doctor, "ROOT", root), \
                 mock.patch.dict("os.environ", {"LOCAL_AI_RUNTIME_ROOT": str(runtime)}, clear=False), \
                 mock.patch("commands.doctor.install.all_manifests", return_value={0: {"directory": "stack0"}}), \
                 mock.patch("commands.doctor.install.load_lifecycle", return_value={"stacks": {"0": {}}}), \
                 mock.patch("commands.doctor.install.validate_registry") as validate, \
                 mock.patch("commands.doctor.shutil.which", return_value="/usr/bin/docker"), \
                 mock.patch("commands.doctor.subprocess.run", return_value=compose):
                checks = doctor.run_checks()

        validate.assert_called_once()
        statuses = {item["id"]: item["status"] for item in checks}
        self.assertEqual(statuses, {
            "management_entrypoint": "pass",
            "lifecycle_registry": "pass",
            "operational_env": "pass",
            "docker_cli": "pass",
            "docker_compose": "pass",
            "runtime_root": "pass",
        })

    def test_json_main_returns_machine_contract(self):
        checks = [{"id": "x", "status": "pass", "message": "ok", "details": {}}]
        with mock.patch("commands.doctor.run_checks", return_value=checks), \
             mock.patch("builtins.print") as output:
            rc = doctor.main(json_output=True)
        self.assertEqual(rc, 0)
        rendered = json.loads(output.call_args.args[0])
        self.assertEqual(rendered["command"], "doctor")
        self.assertTrue(rendered["success"])


if __name__ == "__main__":
    unittest.main()
