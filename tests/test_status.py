from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
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

    def test_drift_compares_installation_desired_with_runtime_actual(self):
        self.assertEqual(status._drift("v1", "v1"), "ok")
        self.assertEqual(status._drift("v1", "v2"), "drift")
        self.assertEqual(status._drift("v1", "n/a"), "drift")
        self.assertEqual(status._drift("n/a", "n/a"), "unknown")

    def test_inventory_keeps_desired_deployed_and_actual_separate(self):
        component = mock.Mock(stack="stack6", name="hermes")
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            with mock.patch("commands.status.upgrade.load_catalog", return_value=[component]), \
                 mock.patch("commands.status.upgrade.read_env", return_value={}), \
                 mock.patch("commands.status.upgrade.compose_image", return_value="repo:v2"), \
                 mock.patch("commands.status.upgrade.running_image", return_value="repo:v1"), \
                 mock.patch("commands.status.upgrade.runtime_root", return_value=runtime), \
                 mock.patch("commands.status._deployed_versions", return_value={"stack6/hermes": "v1"}):
                rows = status.inventory()
        self.assertEqual(rows[0]["desired"], "v2")
        self.assertEqual(rows[0]["deployed"], "v1")
        self.assertEqual(rows[0]["actual"], "v1")
        self.assertEqual(rows[0]["drift"], "drift")

    def test_inventory_uses_runtime_root_for_deployed_history(self):
        component = mock.Mock(stack="stack6", name="hermes")
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
                 mock.patch("commands.status.upgrade.running_image", return_value="repo:v3"), \
                 mock.patch("commands.status.upgrade.runtime_root", return_value=runtime):
                rows = status.inventory()
        self.assertEqual(rows[0]["deployed"], "v3")
        self.assertEqual(rows[0]["drift"], "ok")


if __name__ == "__main__":
    unittest.main()
