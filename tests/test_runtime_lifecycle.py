from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

from commands import runtime_lifecycle


class CP:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class RuntimeLifecycleTests(unittest.TestCase):
    def manifests(self):
        return {
            0: {"id": 0, "directory": "stack0", "requires": [], "provides": ["platform"]},
            1: {"id": 1, "directory": "stack1", "requires": [0], "provides": ["ingress"]},
            3: {"id": 3, "directory": "stack3", "requires": [0], "provides": ["ai.gateway"]},
            7: {"id": 7, "directory": "stack7", "requires": [0, 3], "consumes": ["ai.gateway"], "provides": ["ai.chat-ui"]},
        }

    def lifecycle(self):
        return {"schema_version": 1, "stacks": {
            "0": {"directory": "stack0", "required_containers": []},
            "1": {"directory": "stack1", "required_containers": ["haproxy", "web"]},
            "3": {"directory": "stack3", "required_containers": ["litellm-postgres", "litellm"]},
            "7": {"directory": "stack7", "required_containers": ["open-webui"]},
        }}

    def states(self, **values):
        defaults = {
            "haproxy": "running", "web": "running",
            "litellm-postgres": "running/healthy", "litellm": "running/healthy",
            "open-webui": "running/healthy",
        }
        defaults.update(values)
        return defaults

    def execute_with_states(self, action, selector, states):
        manifests = self.manifests()
        lifecycle = self.lifecycle()
        with mock.patch.object(runtime_lifecycle, "_preflight", return_value=(manifests, lifecycle)), \
             mock.patch("commands.runtime_lifecycle.install.stack_prepared", return_value=True), \
             mock.patch("commands.runtime_lifecycle.install.container_state", side_effect=lambda name: states.get(name, "absent")), \
             mock.patch("commands.runtime_lifecycle.install.run", return_value=CP()) as run, \
             mock.patch("commands.runtime_lifecycle.install.wait_required_runtime") as wait:
            result = runtime_lifecycle.execute(action, selector)
        return result, run, wait

    def test_start_uses_compose_start_and_waits_for_required_runtime(self):
        result, run, wait = self.execute_with_states("start", "7", self.states(open_webui="exited"))
        self.assertEqual(result.stack_id, 7)
        command = run.call_args.args[0]
        self.assertEqual(command, ["docker", "compose", "start"])
        self.assertTrue(str(run.call_args.kwargs["cwd"]).endswith("stack7"))
        wait.assert_called_once()

    def test_start_rejects_missing_required_provider_without_starting_it(self):
        states = self.states(litellm="exited", open_webui="exited")
        with mock.patch.object(runtime_lifecycle, "_preflight", return_value=(self.manifests(), self.lifecycle())), \
             mock.patch("commands.runtime_lifecycle.install.stack_prepared", return_value=True), \
             mock.patch("commands.runtime_lifecycle.install.container_state", side_effect=lambda name: states.get(name, "absent")), \
             mock.patch("commands.runtime_lifecycle.install.run") as run:
            with self.assertRaises(runtime_lifecycle.RuntimeLifecycleError) as raised:
                runtime_lifecycle.execute("start", "7")
        self.assertEqual(raised.exception.code, "STACK_DEPENDENCY_NOT_RUNNING")
        run.assert_not_called()

    def test_stop_rejects_provider_with_active_required_consumer(self):
        with mock.patch.object(runtime_lifecycle, "_preflight", return_value=(self.manifests(), self.lifecycle())), \
             mock.patch("commands.runtime_lifecycle.install.stack_prepared", return_value=True), \
             mock.patch("commands.runtime_lifecycle.install.container_state", side_effect=lambda name: self.states().get(name, "absent")), \
             mock.patch("commands.runtime_lifecycle.install.run") as run:
            with self.assertRaises(runtime_lifecycle.RuntimeLifecycleError) as raised:
                runtime_lifecycle.execute("stop", "3")
        self.assertEqual(raised.exception.code, "STACK_HAS_ACTIVE_CONSUMERS")
        self.assertIn("stack7", raised.exception.message)
        run.assert_not_called()

    def test_stop_leaf_stack_uses_compose_stop_without_destructive_action(self):
        result, run, wait = self.execute_with_states("stop", "7", self.states())
        self.assertEqual(result.stack_id, 7)
        self.assertEqual(run.call_args.args[0], ["docker", "compose", "stop"])
        wait.assert_not_called()

    def test_stack_without_runtime_is_rejected(self):
        with mock.patch.object(runtime_lifecycle, "_preflight", return_value=(self.manifests(), self.lifecycle())):
            with self.assertRaises(runtime_lifecycle.RuntimeLifecycleError) as raised:
                runtime_lifecycle.execute("stop", "0")
        self.assertEqual(raised.exception.code, "STACK_RUNTIME_EMPTY")

    def test_json_failure_contract_has_stable_code(self):
        error = runtime_lifecycle.RuntimeLifecycleError("STACK_DEPENDENCY_NOT_RUNNING", "missing")
        with mock.patch("commands.runtime_lifecycle.execute", side_effect=error), redirect_stdout(io.StringIO()) as stdout:
            rc = runtime_lifecycle.main("start", "7", json_output=True)
        self.assertEqual(rc, 1)
        self.assertIn('"code": "STACK_DEPENDENCY_NOT_RUNNING"', stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
