#!/usr/bin/env python3
"""Lifecycle-contract tests for Stack6 restart reconciliation and readiness.

These tests ensure capability reconciliation that restarts Hermes is followed by
an explicit READY wait before verification, that the wait script covers all
required Stack6 runtime containers, and that lifecycle commands invoked directly
by the registry are actually executable.
"""

import json
import os
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE = ROOT / "commands" / "install-lifecycle.json"
WAIT_SCRIPT = ROOT / "stack6_-_hermes" / "07-wait-ready.sh"


class Stack6ReconcileReadyContractTests(unittest.TestCase):
    def test_stack6_reconcile_waits_for_ready_before_verify(self):
        data = json.loads(LIFECYCLE.read_text(encoding="utf-8"))
        reconcile = data["stacks"]["6"]["reconcile"]
        self.assertEqual(
            reconcile,
            [
                ["bash", "./06-reconcile-capabilities.sh", "--restart"],
                ["bash", "./07-wait-ready.sh"],
            ],
        )

    def test_wait_script_is_present_and_checks_required_runtime(self):
        text = WAIT_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("HERMES_CONTAINER", text)
        self.assertIn("SANDBOX_CONTAINER", text)
        self.assertIn("SANDBOX_CLEANUP_CONTAINER", text)
        self.assertIn("healthy", text)
        self.assertIn("running", text)
        self.assertIn("TIMEOUT_SECONDS", text)

    def test_lifecycle_direct_script_commands_are_executable(self):
        data = json.loads(LIFECYCLE.read_text(encoding="utf-8"))
        failures = []
        for sid, entry in data["stacks"].items():
            stack_dir = ROOT / entry["directory"]
            for phase in ("prepare", "deploy", "reconcile", "verify"):
                for command in entry[phase]:
                    if not command or not command[0].startswith("./"):
                        continue
                    script = stack_dir / command[0][2:]
                    if not script.is_file() or not os.access(script, os.X_OK):
                        failures.append(f"stack{sid} {phase}: {command[0]}")
        self.assertEqual(failures, [], f"direct lifecycle scripts must be executable: {failures}")


if __name__ == "__main__":
    unittest.main()
