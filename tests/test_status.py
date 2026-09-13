from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from commands import status
from commands import upgrade_registry


class StatusStateTests(unittest.TestCase):
    def test_deployed_version_comes_from_latest_success_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            platform = root / "platform"
            platform.mkdir(parents=True)
            events = [
                {
                    "success": True,
                    "upgraded": [{"stack": "stack6", "component": "hermes", "version": "v1"}],
                },
                {
                    "success": False,
                    "selected": [{"stack": "stack6", "component": "hermes", "version": "v2"}],
                },
                {
                    "success": True,
                    "upgraded": [{"stack": "stack6", "component": "hermes", "version": "v3"}],
                },
            ]
            (platform / "upgrade-history.jsonl").write_text(
                "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
            )
            deployed = status._deployed_versions(root)
        self.assertEqual(deployed["stack6/hermes"], "v3")

    def test_deployed_prefers_recorded_history(self):
        self.assertEqual(
            status._deployed("stack6/hermes", "v3", "v3", {"stack6/hermes": "v2"}),
            "v2",
        )

    def test_deployed_adopts_observed_runtime_when_history_is_absent(self):
        self.assertEqual(status._deployed("stack7/open-webui", "v0.11.3", "v0.11.3", {}), "v0.11.3")
        self.assertEqual(status._deployed("stack7/open-webui", "v0.12.0", "v0.11.3", {}), "v0.11.3")
        self.assertEqual(status._deployed("stack6/sandbox", "local", "local", {}), "local")

    def test_deployed_uses_na_only_when_deployment_version_is_not_applicable(self):
        self.assertEqual(status._deployed("stack0/platform-foundation", "n/a", "n/a", {}), "n/a")
        self.assertEqual(status._deployed("stack7/open-webui", "v0.11.3", "n/a", {}), "unknown")

    def test_drift_is_quick_yes_no_or_na_decision(self):
        self.assertEqual(status._drift("v1", "v1"), "no")
        self.assertEqual(status._drift("v1", "v2"), "yes")
        self.assertEqual(status._drift("v1", "n/a"), "yes")
        self.assertEqual(status._drift("n/a", "n/a"), "n/a")
        self.assertEqual(status._drift("n/a", "v1"), "n/a")

    def test_floating_reference_detection_distinguishes_tracking_from_fixed_tags(self):
        self.assertTrue(status._is_floating_image_reference("redis:alpine"))
        self.assertTrue(status._is_floating_image_reference("rabbitmq:3-alpine"))
        self.assertTrue(status._is_floating_image_reference("haproxy:3.0-alpine"))
        self.assertFalse(status._is_floating_image_reference("ghcr.io/open-webui/open-webui:v0.11.3"))
        self.assertFalse(status._is_floating_image_reference("searxng/searxng:2026.9.5-c7f3080aa"))
        self.assertFalse(status._is_floating_image_reference("postgres:17.10-alpine@sha256:abcd"))

    def test_inventory_keeps_desired_deployed_and_actual_separate(self):
        component = SimpleNamespace(stack="stack6", name="hermes")
        with mock.patch("commands.status.upgrade.load_catalog", return_value=[component]), \
             mock.patch("commands.status.upgrade.read_env", return_value={}), \
             mock.patch("commands.status.upgrade.compose_image", return_value="repo:v2.0.0"), \
             mock.patch("commands.status.upgrade.running_image", return_value="repo:v1.0.0"):
            rows = status.inventory(deployed_versions={"stack6/hermes": "v1.0.0"})
        self.assertEqual(rows[0]["desired"], "v2.0.0")
        self.assertEqual(rows[0]["deployed"], "v1.0.0")
        self.assertEqual(rows[0]["actual"], "v1.0.0")
        self.assertEqual(rows[0]["drift"], "yes")

    def test_inventory_adopts_actual_as_pre_history_deployment_baseline(self):
        component = SimpleNamespace(stack="stack7", name="open-webui")
        with mock.patch("commands.status.upgrade.load_catalog", return_value=[component]), \
             mock.patch("commands.status.upgrade.read_env", return_value={}), \
             mock.patch("commands.status.upgrade.compose_image", return_value="repo:v0.11.3"), \
             mock.patch("commands.status.upgrade.running_image", return_value="repo:v0.11.3"):
            rows = status.inventory(deployed_versions={})
        self.assertEqual(rows[0]["desired"], "v0.11.3")
        self.assertEqual(rows[0]["deployed"], "v0.11.3")
        self.assertEqual(rows[0]["actual"], "v0.11.3")
        self.assertEqual(rows[0]["drift"], "no")

    def test_inventory_resolves_floating_tag_to_registry_identities(self):
        component = SimpleNamespace(stack="stack2", name="redis", container="firecrawl-redis")
        state = SimpleNamespace(
            current_version="8.10.0-alpine3.23",
            available_version="8.10.1-alpine3.23",
            local_digest="sha256:old",
            remote_digest="sha256:new",
        )
        with mock.patch("commands.status.upgrade.load_catalog", return_value=[component]), \
             mock.patch("commands.status.upgrade.read_env", return_value={}), \
             mock.patch("commands.status.upgrade.compose_image", return_value="redis:alpine"), \
             mock.patch("commands.status.upgrade.running_image", return_value="redis:alpine"), \
             mock.patch("commands.status.upgrade_registry.inspect", return_value=state) as inspect_mock:
            rows = status.inventory(deployed_versions={})
        inspect_mock.assert_called_once_with("firecrawl-redis", "redis:alpine", tracking_image="redis:alpine")
        self.assertEqual(rows[0]["desired"], "8.10.1-alpine3.23")
        self.assertEqual(rows[0]["deployed"], "8.10.0-alpine3.23")
        self.assertEqual(rows[0]["actual"], "8.10.0-alpine3.23")
        self.assertEqual(rows[0]["drift"], "yes")

    def test_floating_tag_registry_failure_never_claims_no_drift(self):
        component = SimpleNamespace(stack="stack2", name="redis", container="firecrawl-redis")
        with mock.patch("commands.status.upgrade.load_catalog", return_value=[component]), \
             mock.patch("commands.status.upgrade.read_env", return_value={}), \
             mock.patch("commands.status.upgrade.compose_image", return_value="redis:alpine"), \
             mock.patch("commands.status.upgrade.running_image", return_value="redis:alpine"), \
             mock.patch("commands.status.upgrade_registry.inspect", side_effect=upgrade_registry.RegistryError("rate limited")):
            rows = status.inventory(deployed_versions={})
        self.assertEqual(rows[0]["desired"], "alpine")
        self.assertEqual(rows[0]["actual"], "alpine")
        self.assertEqual(rows[0]["drift"], "n/a")

    def test_inventory_uses_explicit_runtime_root_for_deployed_history(self):
        component = SimpleNamespace(stack="stack6", name="hermes")
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            platform = runtime / "platform"
            platform.mkdir(parents=True)
            (platform / "upgrade-history.jsonl").write_text(json.dumps({
                "success": True,
                "upgraded": [{"stack": "stack6", "component": "hermes", "version": "v3.0.0"}],
            }) + "\n", encoding="utf-8")
            with mock.patch("commands.status.upgrade.load_catalog", return_value=[component]), \
                 mock.patch("commands.status.upgrade.read_env", return_value={}), \
                 mock.patch("commands.status.upgrade.compose_image", return_value="repo:v3.0.0"), \
                 mock.patch("commands.status.upgrade.running_image", return_value="repo:v3.0.0"):
                rows = status.inventory(runtime_root=runtime)
        self.assertEqual(rows[0]["deployed"], "v3.0.0")
        self.assertEqual(rows[0]["drift"], "no")


if __name__ == "__main__":
    unittest.main()
