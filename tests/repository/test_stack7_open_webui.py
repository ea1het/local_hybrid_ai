# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Static contract tests for Stack7 ownership, lifecycle, policy and recovery.

These tests keep the manifest gateway dependency, internal-only networking,
fresh-instance defaults, bootstrap-safe policy reconciliation/verification and
quiesced sensitive DR archive aligned. They protect the declarative Stack7
contract without requiring a live Open WebUI instance.
"""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STACK = ROOT / "stack7_-_open-webui"
LIFECYCLE = ROOT / "src" / "local_ai_cli" / "install-lifecycle.json"


class Stack7OpenWebUIContractTests(unittest.TestCase):
    def test_manifest_is_atomic_and_gateway_driven(self):
        data = json.loads((STACK / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(data["id"], 7)
        self.assertTrue(data["atomic"])
        self.assertEqual(data["requires"], [0, 3])
        self.assertEqual(data["target_requires"], [0, 3])
        self.assertIn(1, data["optional"])
        self.assertEqual(data["consumes"], ["ai.gateway"])
        self.assertIn("ai.chat-ui", data["provides"])
        self.assertIn("container:open-webui", data["owns"])

    def test_lifecycle_has_stack_owned_readiness_and_policy(self):
        lifecycle = json.loads(LIFECYCLE.read_text(encoding="utf-8"))["stacks"]["7"]
        self.assertEqual(lifecycle["directory"], "stack7_-_open-webui")
        self.assertEqual(lifecycle["required_containers"], ["open-webui"])
        self.assertIn(["bash", "./02-wait-ready.sh"], lifecycle["deploy"])
        self.assertIn(["python3", "./03-reconcile-model-policy.py"], lifecycle["reconcile"])
        self.assertIn(["bash", "./02-wait-ready.sh"], lifecycle["verify"])
        self.assertIn(["python3", "./04-verify-model-policy.py"], lifecycle["verify"])

    def test_compose_has_no_host_ports_and_uses_litellm(self):
        compose = (STACK / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertNotIn("ports:", compose)
        self.assertIn("OPENAI_API_BASE_URL", compose)
        self.assertIn("OPENWEBUI_LITELLM_BASE_URL", compose)
        self.assertIn("OPENWEBUI_LITELLM_API_KEY", compose)
        self.assertIn("WEBUI_SECRET_KEY", compose)
        self.assertIn("/app/backend/data", compose)
        self.assertIn("ENABLE_OLLAMA_API: \"false\"", compose)

    def test_compose_seeds_expected_fresh_instance_defaults(self):
        compose = (STACK / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn('DEFAULT_MODELS: "basic_autorouter"', compose)
        self.assertIn('ENABLE_EVALUATION_ARENA_MODELS: "false"', compose)
        self.assertIn("DEFAULT_INTERFACE_SETTINGS: '{\"webSearch\":\"always\"}'", compose)
        self.assertNotIn("ENABLE_PERSISTENT_CONFIG", compose)
        self.assertNotIn("BYPASS_MODEL_ACCESS_CONTROL", compose)

    def test_model_policy_reconciler_is_stack_owned_and_bootstrap_safe(self):
        reconcile = (STACK / "03-reconcile-model-policy.py").read_text(encoding="utf-8")
        self.assertIn('MODEL_ID = "basic_autorouter"', reconcile)
        self.assertIn('"web_search": True', reconcile)
        self.assertIn('"defaultFeatureIds": ["web_search"]', reconcile)
        self.assertIn('principal_id="*"', reconcile)
        self.assertIn('permission="read"', reconcile)
        self.assertIn("DEFER basic_autorouter policy reconciliation", reconcile)
        self.assertNotIn("sqlite3", reconcile)
        self.assertNotIn("BYPASS_MODEL_ACCESS_CONTROL", reconcile)

    def test_model_policy_verifier_is_read_only_and_bootstrap_safe(self):
        verify = (STACK / "04-verify-model-policy.py").read_text(encoding="utf-8")
        self.assertIn("get_grants_by_resource", verify)
        self.assertIn('"web_search" not in feature_ids', verify)
        self.assertIn("DEFER basic_autorouter policy verification", verify)
        self.assertNotIn("grant_access(", verify)
        self.assertNotIn("db.commit", verify)
        self.assertNotIn("sqlite3", verify)

    def test_recovery_uses_quiesced_sensitive_archive(self):
        data = json.loads((STACK / "manifest.json").read_text(encoding="utf-8"))
        resource = next(r for r in data["recovery"]["resources"] if r["id"] == "open-webui-data")
        self.assertEqual(resource["strategy"], "archive")
        self.assertTrue(resource["sensitive"])
        self.assertEqual(resource["config"]["quiesce_container"], "open-webui")
        self.assertEqual(resource["config"]["restore"]["phase"], "post-prepare-pre-deploy")


if __name__ == "__main__":
    unittest.main()
