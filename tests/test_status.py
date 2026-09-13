from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from commands import status


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

    def test_inventory_keeps_desired_deployed_and_actual_separate(self):
        component = SimpleNamespace(stack="stack6", name="hermes")
        with mock.patch("commands.status.upgrade.load_catalog", return_value=[component]), \
             mock.patch("commands.status.upgrade.read_env", return_value={}), \
             mock.patch("commands.status.upgrade.compose_image", return_value="repo:v2"), \
             mock.patch("commands.status.upgrade.running_image", return_value="repo:v1"):
            rows = status.inventory(deployed_versions={"stack6/hermes": "v1"})
        self.assertEqual(rows[0]["desired"], "v2")
        self.assertEqual(rows[0]["deployed"], "v1")
        self.assertEqual(rows[0]["actual"], "v1")
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

    def test_inventory_uses_explicit_runtime_root_for_deployed_history(self):
        component = SimpleNamespace(stack="stack6", name="hermes")
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            platform = runtime / "platform"
            platform.mkdir(parents=True)
            (platform / "upgrade-history.jsonl").write_text(json.dumps({
                "success": True,
                "upgraded": [{"stack": "stack6", "component": "hermes", "version": "v3"}],
            }) + "\n", encoding="utf-8")
            with mock.patch("commands.status.upgrade.load_catalog", return_value=[component]), \
                 mock.patch("commands.status.upgrade.read_env", return_value={}), \
                 mock.patch("commands.status.upgrade.compose_image", return_value="repo:v3"), \
                 mock.patch("commands.status.upgrade.running_image", return_value="repo:v3"):
                rows = status.inventory(runtime_root=runtime)
        self.assertEqual(rows[0]["deployed"], "v3")
        self.assertEqual(rows[0]["drift"], "no")


if __name__ == "__main__":
    unittest.main()
