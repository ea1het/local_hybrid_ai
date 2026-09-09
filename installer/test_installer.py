#!/usr/bin/env python3
import unittest
from unittest.mock import patch

import install


MANIFESTS = {
    0: {
        "id": 0,
        "directory": "stack0_-_platform",
        "provides": ["platform.foundation"],
        "optional_consumes": [],
        "owns": [],
    },
    2: {
        "id": 2,
        "directory": "stack2_-_searxng_firecrawl",
        "provides": ["web.search", "web.extract"],
        "optional_consumes": [],
        "owns": ["container:searxng", "container:firecrawl-api"],
    },
    4: {
        "id": 4,
        "directory": "stack4_-_gitea",
        "provides": ["git.remote", "git.runner"],
        "optional_consumes": [],
        "owns": ["container:gitea", "container:gitea-runner"],
    },
    6: {
        "id": 6,
        "directory": "stack6_-_hermes",
        "provides": ["ai.agent"],
        "optional_consumes": ["web.search", "web.extract", "git.remote"],
        "owns": ["container:hermes", "container:hermes-sandbox"],
    },
}

LIFECYCLE = {
    "stacks": {
        "0": {
            "required_containers": [],
            "prepare": [["./01-prepare.sh"]],
            "deploy": [],
            "reconcile": [],
            "verify": [["./verify.sh"]],
        },
        "2": {
            "required_containers": ["searxng", "firecrawl-api"],
            "prepare": [["./01-prepare.sh"]],
            "deploy": [["docker", "compose", "up", "-d"]],
            "reconcile": [],
            "verify": [["docker", "compose", "config", "--quiet"]],
        },
        "4": {
            "required_containers": ["gitea", "gitea-runner"],
            "prepare": [["./01-prepare.sh"]],
            "deploy": [["./02-run.sh"]],
            "reconcile": [],
            "verify": [["docker", "compose", "config", "--quiet"]],
        },
        "6": {
            "required_containers": ["hermes", "hermes-sandbox"],
            "prepare": [["./01-prepare.sh"]],
            "deploy": [["docker", "compose", "up", "-d"]],
            "reconcile": [["./06-reconcile-capabilities.sh", "--restart"]],
            "verify": [["docker", "compose", "config", "--quiet"]],
        },
    }
}


def state(prepared: bool, **containers: str) -> dict:
    return {"prepared": prepared, "containers": containers}


class InstallerPlannerTests(unittest.TestCase):
    def build(self, requested, plan, states, force_reconcile=False):
        with patch("install.stack_state", side_effect=lambda manifest: states[manifest["id"]]), \
             patch("install.stack_prepared", side_effect=lambda directory: next(
                 states[sid]["prepared"] for sid, manifest in MANIFESTS.items()
                 if manifest["directory"] == directory
             )):
            return install.build_actions(
                requested,
                plan,
                MANIFESTS,
                LIFECYCLE,
                force_reconcile=force_reconcile,
            )

    def phases(self, actions):
        return [(action.stack_id, action.phase) for action in actions]

    def test_healthy_requested_consumer_only_verifies(self):
        states = {
            0: state(True),
            6: state(True, hermes="running/healthy", **{"hermes-sandbox": "running/healthy"}),
        }
        actions, reconcile, changed = self.build([6], [0, 6], states)
        self.assertEqual(changed, set())
        self.assertEqual(reconcile, [])
        self.assertNotIn((6, "deploy"), self.phases(actions))
        self.assertNotIn((6, "ready"), self.phases(actions))
        self.assertNotIn((6, "reconcile"), self.phases(actions))
        self.assertEqual(self.phases(actions), [(0, "verify"), (6, "verify")])

    def test_new_consumer_prepares_deploys_waits_and_reconciles(self):
        states = {
            0: state(True),
            6: state(False, hermes="absent", **{"hermes-sandbox": "absent"}),
        }
        actions, reconcile, changed = self.build([6], [0, 6], states)
        self.assertEqual(changed, {6})
        self.assertEqual(reconcile, [6])
        phases = self.phases(actions)
        self.assertIn((6, "prepare"), phases)
        self.assertIn((6, "deploy"), phases)
        self.assertIn((6, "ready"), phases)
        self.assertIn((6, "reconcile"), phases)
        self.assertLess(phases.index((6, "deploy")), phases.index((6, "ready")))
        self.assertLess(phases.index((6, "ready")), phases.index((6, "reconcile")))

    def test_healthy_provider_does_not_reconcile_consumer(self):
        states = {
            0: state(True),
            2: state(True, searxng="running", **{"firecrawl-api": "running"}),
            6: state(True, hermes="running/healthy", **{"hermes-sandbox": "running/healthy"}),
        }
        actions, reconcile, changed = self.build([2], [0, 2], states)
        self.assertEqual(changed, set())
        self.assertEqual(reconcile, [])
        self.assertNotIn((2, "ready"), self.phases(actions))
        self.assertNotIn((6, "reconcile"), self.phases(actions))

    def test_new_web_provider_waits_before_reconciling_prepared_consumer(self):
        states = {
            0: state(True),
            2: state(False, searxng="absent", **{"firecrawl-api": "absent"}),
            6: state(True, hermes="running/healthy", **{"hermes-sandbox": "running/healthy"}),
        }
        actions, reconcile, changed = self.build([2], [0, 2], states)
        self.assertEqual(changed, {2})
        self.assertEqual(reconcile, [6])
        phases = self.phases(actions)
        self.assertIn((2, "deploy"), phases)
        self.assertIn((2, "ready"), phases)
        self.assertIn((6, "reconcile"), phases)
        self.assertLess(phases.index((2, "deploy")), phases.index((2, "ready")))
        self.assertLess(phases.index((2, "ready")), phases.index((6, "reconcile")))

    def test_new_git_provider_waits_before_reconciling_prepared_consumer(self):
        states = {
            0: state(True),
            4: state(False, gitea="absent", **{"gitea-runner": "absent"}),
            6: state(True, hermes="running/healthy", **{"hermes-sandbox": "running/healthy"}),
        }
        actions, reconcile, changed = self.build([4], [0, 4], states)
        self.assertEqual(changed, {4})
        self.assertEqual(reconcile, [6])
        phases = self.phases(actions)
        self.assertIn((4, "ready"), phases)
        self.assertIn((6, "reconcile"), phases)
        self.assertLess(phases.index((4, "ready")), phases.index((6, "reconcile")))

    def test_force_reconcile_is_explicit_override(self):
        states = {
            0: state(True),
            6: state(True, hermes="running/healthy", **{"hermes-sandbox": "running/healthy"}),
        }
        actions, reconcile, changed = self.build([6], [0, 6], states, force_reconcile=True)
        self.assertEqual(changed, set())
        self.assertEqual(reconcile, [6])
        self.assertIn((6, "reconcile"), self.phases(actions))
        self.assertNotIn((6, "deploy"), self.phases(actions))
        self.assertNotIn((6, "ready"), self.phases(actions))

    def test_wait_required_runtime_accepts_starting_then_healthy(self):
        states = iter([
            "running/starting",
            "running/starting",
            "running/healthy",
            "running/healthy",
        ])
        with patch("install.container_state", side_effect=lambda name: next(states)), \
             patch("install.time.sleep"):
            install.wait_required_runtime(
                3,
                {"required_containers": ["litellm-postgres", "litellm"]},
                timeout_seconds=10,
            )

    def test_wait_required_runtime_fails_fast_on_exited_container(self):
        with patch("install.container_state", return_value="exited"):
            with self.assertRaises(install.InstallerError):
                install.wait_required_runtime(
                    2,
                    {"required_containers": ["searxng"]},
                    timeout_seconds=10,
                )


if __name__ == "__main__":
    unittest.main()
