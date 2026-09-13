from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from internal import version_sources

ROOT = Path(__file__).resolve().parents[1]


class VersionSourceTests(unittest.TestCase):
    def test_components_without_adapter_are_not_guessed(self):
        self.assertEqual(version_sources.available_version({}, online=True), "n/a")

    def test_offline_never_queries_source(self):
        component = {"version_source": {"type": "github_release", "repo": "owner/repo"}}
        with mock.patch("internal.version_sources._github_latest") as latest:
            self.assertEqual(version_sources.available_version(component, online=False), "unchecked")
        latest.assert_not_called()

    def test_hermes_release_tag_maps_directly_to_image_version(self):
        component = {"version_source": {"type": "github_release", "repo": "NousResearch/hermes-agent"}}
        with mock.patch("internal.version_sources._github_latest", return_value="v2026.9.11"):
            self.assertEqual(version_sources.available_version(component, online=True), "v2026.9.11")

    def test_gitea_release_tag_maps_to_rootless_image_version(self):
        component = {"version_source": {
            "type": "github_release", "repo": "go-gitea/gitea", "strip_prefix": "v", "suffix": "-rootless"
        }}
        with mock.patch("internal.version_sources._github_latest", return_value="v1.27.3"):
            self.assertEqual(version_sources.available_version(component, online=True), "1.27.3-rootless")

    def test_catalog_declares_only_intentional_first_adapters(self):
        catalog = json.loads((ROOT / "internal" / "upgrade-components.json").read_text(encoding="utf-8"))
        adapted = {
            f"{stack['id']}/{component['id']}"
            for stack in catalog["stacks"]
            for component in stack["components"]
            if "version_source" in component
        }
        self.assertEqual(adapted, {
            "stack4/gitea", "stack5/dockhand", "stack6/hermes", "stack7/open-webui"
        })


if __name__ == "__main__":
    unittest.main()
