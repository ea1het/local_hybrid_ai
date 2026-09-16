# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Stable JSON-contract tests for install, doctor and restore management commands.

The tests exercise the public management facade with private engines mocked at
the boundary so machine-readable output cannot regress into human-only text.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from unittest import mock

from commands import cli, install_entry


class ManagementJsonContractTests(unittest.TestCase):
    def test_install_plan_json_exposes_high_level_lifecycle_without_private_commands(self):
        manifests = {7: {"directory": "stack7_-_open-webui"}}
        lifecycle = {"stacks": {"7": {}}}
        action = mock.Mock(stack_id=7, phase="verify", reason="validate stack-owned contract")
        with mock.patch("commands.install_entry.install.preflight"), \
             mock.patch("commands.install_entry.install.all_manifests", return_value=manifests), \
             mock.patch("commands.install_entry.install.load_lifecycle", return_value=lifecycle), \
             mock.patch("commands.install_entry.install.validate_registry"), \
             mock.patch("commands.install_entry.install.resolve_requested", return_value=[7]), \
             mock.patch("commands.install_entry.install.resolve_plan", return_value=[7]), \
             mock.patch("commands.install_entry.install.build_actions", return_value=([action], [], set())):
            payload, rc = install_entry.build_payload(["7", "--plan"])

        self.assertEqual(rc, 0)
        self.assertEqual(payload["schema_version"], "1")
        self.assertEqual(payload["command"], "install")
        self.assertEqual(payload["mode"], "plan")
        self.assertEqual(payload["resolved_stacks"], ["stack7"])
        self.assertEqual(payload["actions"], [{"stack": "stack7", "phase": "verify", "reason": "validate stack-owned contract"}])
        self.assertNotIn("command_line", payload["actions"][0])

    def test_install_execute_requires_explicit_yes_in_json_mode(self):
        manifests = {7: {"directory": "stack7_-_open-webui"}}
        lifecycle = {"stacks": {"7": {}}}
        with mock.patch("commands.install_entry.install.preflight"), \
             mock.patch("commands.install_entry.install.all_manifests", return_value=manifests), \
             mock.patch("commands.install_entry.install.load_lifecycle", return_value=lifecycle), \
             mock.patch("commands.install_entry.install.validate_registry"), \
             mock.patch("commands.install_entry.install.resolve_requested", return_value=[7]), \
             mock.patch("commands.install_entry.install.resolve_plan", return_value=[7]), \
             mock.patch("commands.install_entry.install.build_actions", return_value=([], [], set())):
            payload, rc = install_entry.build_payload(["7"])
        self.assertEqual(rc, 1)
        self.assertEqual(payload["error"]["code"], "INSTALL_CONFIRMATION_REQUIRED")

    def test_restore_json_wraps_private_result_in_stable_public_envelope(self):
        completed = subprocess.CompletedProcess(args=["python"], returncode=0, stdout=json.dumps({"resolved_stacks": [0, 1]}), stderr="")
        with mock.patch("commands.cli.subprocess.run", return_value=completed), mock.patch("builtins.print") as output:
            rc = cli.restore_command(["plan", "/backup"], True)
        self.assertEqual(rc, 0)
        payload = json.loads(output.call_args.args[0])
        self.assertEqual(payload["schema_version"], "1")
        self.assertEqual(payload["command"], "restore.plan")
        self.assertTrue(payload["success"])
        self.assertEqual(payload["result"]["resolved_stacks"], [0, 1])

    def test_restore_json_failure_does_not_leak_human_stderr_outside_json(self):
        completed = subprocess.CompletedProcess(args=["python"], returncode=1, stdout="", stderr="restore failed")
        with mock.patch("commands.cli.subprocess.run", return_value=completed), mock.patch("builtins.print") as output:
            rc = cli.restore_command(["plan", "/backup"], True)
        self.assertEqual(rc, 1)
        payload = json.loads(output.call_args.args[0])
        self.assertFalse(payload["success"])
        self.assertEqual(payload["command"], "restore.plan")
        self.assertEqual(payload["error"]["code"], "INTERNAL_COMMAND_FAILED")


if __name__ == "__main__":
    unittest.main()
