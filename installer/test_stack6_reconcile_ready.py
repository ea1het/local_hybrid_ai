#!/usr/bin/env python3
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE = ROOT / "installer" / "lifecycle.json"
WAIT_SCRIPT = ROOT / "stack6_-_hermes" / "07-wait-ready.sh"


class Stack6ReconcileReadyContractTests(unittest.TestCase):
    def test_stack6_reconcile_waits_for_ready_before_verify(self):
        data = json.loads(LIFECYCLE.read_text(encoding="utf-8"))
        reconcile = data["stacks"]["6"]["reconcile"]
        self.assertEqual(
            reconcile,
            [
                ["./06-reconcile-capabilities.sh", "--restart"],
                ["./07-wait-ready.sh"],
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


if __name__ == "__main__":
    unittest.main()
