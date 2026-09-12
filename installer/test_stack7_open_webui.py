import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STACK = ROOT / "stack7_-_open-webui"


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

    def test_lifecycle_has_stack_owned_readiness(self):
        lifecycle = json.loads((ROOT / "installer" / "lifecycle.json").read_text(encoding="utf-8"))["stacks"]["7"]
        self.assertEqual(lifecycle["directory"], "stack7_-_open-webui")
        self.assertEqual(lifecycle["required_containers"], ["open-webui"])
        self.assertIn(["bash", "./02-wait-ready.sh"], lifecycle["deploy"])
        self.assertIn(["bash", "./02-wait-ready.sh"], lifecycle["verify"])

    def test_compose_has_no_host_ports_and_uses_litellm(self):
        compose = (STACK / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertNotIn("ports:", compose)
        self.assertIn("OPENAI_API_BASE_URL", compose)
        self.assertIn("OPENWEBUI_LITELLM_BASE_URL", compose)
        self.assertIn("OPENWEBUI_LITELLM_API_KEY", compose)
        self.assertIn("WEBUI_SECRET_KEY", compose)
        self.assertIn("/app/backend/data", compose)
        self.assertIn("ENABLE_OLLAMA_API: \"false\"", compose)

    def test_recovery_uses_quiesced_sensitive_archive(self):
        data = json.loads((STACK / "manifest.json").read_text(encoding="utf-8"))
        resource = next(r for r in data["recovery"]["resources"] if r["id"] == "open-webui-data")
        self.assertEqual(resource["strategy"], "archive")
        self.assertTrue(resource["sensitive"])
        self.assertEqual(resource["config"]["quiesce_container"], "open-webui")
        self.assertEqual(resource["config"]["restore"]["phase"], "post-prepare-pre-deploy")


if __name__ == "__main__":
    unittest.main()
