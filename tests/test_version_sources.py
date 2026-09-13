from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from commands import upgrade
from internal import container_registry, version_sources

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

    def _inventory_component(self):
        return upgrade.Component(
            stack="stack1", name="haproxy", service=None, container="haproxy",
            compose=None, upstream="haproxy/haproxy", selectable=False,
        )

    def _inventory(self, component, record, image, *, online=True, registry_state=None):
        records = {f"{component.stack}/{component.name}": record}
        patches = [
            mock.patch("commands.upgrade.load_catalog", return_value=[component]),
            mock.patch("commands.upgrade.component_records", return_value=records),
            mock.patch("commands.upgrade.read_env", return_value={}),
            mock.patch("commands.upgrade.load_plan", return_value={"schema_version": 1, "selected": {}}),
            mock.patch("commands.upgrade.running_image", return_value=image),
            mock.patch("commands.upgrade.container_registry.inspect", return_value=registry_state),
        ]
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5] as registry:
            return upgrade.inventory(query_upstream=online), registry

    def test_inventory_reports_registry_update_for_unadapted_container(self):
        component = self._inventory_component()
        state = container_registry.RegistryState(
            "haproxy:3.0-alpine", "sha256:old", "sha256:new",
            tracking_image="haproxy:3.0-alpine", remote_status="ok",
        )
        rows, _ = self._inventory(component, {"stack":"stack1","id":"haproxy"}, "haproxy:3.0-alpine", registry_state=state)
        self.assertEqual(rows[0]["available"], "update")
        self.assertEqual(rows[0]["current_display"], "3.0-alpine")
        self.assertTrue(rows[0]["registry"]["update_available"])

    def test_inventory_reports_current_for_equal_registry_digest(self):
        component = self._inventory_component()
        state = container_registry.RegistryState(
            "haproxy:3.0-alpine", "sha256:same", "sha256:same",
            tracking_image="haproxy:3.0-alpine", remote_status="ok",
        )
        rows, _ = self._inventory(component, {"stack":"stack1","id":"haproxy"}, "haproxy:3.0-alpine", registry_state=state)
        self.assertEqual(rows[0]["available"], "current")

    def test_inventory_reports_rate_limit_reason(self):
        component = self._inventory_component()
        state = container_registry.RegistryState(
            "haproxy:3.0-alpine", "sha256:local", None,
            tracking_image="haproxy:3.0-alpine", remote_status="rate_limited",
        )
        rows, _ = self._inventory(component, {"stack":"stack1","id":"haproxy"}, "haproxy:3.0-alpine", registry_state=state)
        self.assertEqual(rows[0]["available"], "unknown")
        self.assertEqual(rows[0]["registry"]["remote_status"], "rate_limited")
        self.assertEqual(upgrade._human_available(rows[0]), "unknown (rate limited)")

    def test_inventory_reports_unknown_when_registry_comparison_is_incomplete(self):
        component = self._inventory_component()
        state = container_registry.RegistryState(
            "haproxy:3.0-alpine", None, "sha256:remote",
            tracking_image="haproxy:3.0-alpine", remote_status="ok",
        )
        rows, _ = self._inventory(component, {"stack":"stack1","id":"haproxy"}, "haproxy:3.0-alpine", registry_state=state)
        self.assertEqual(rows[0]["available"], "unknown")

    def test_inventory_offline_does_not_query_registry(self):
        component = self._inventory_component()
        rows, registry = self._inventory(component, {"stack":"stack1","id":"haproxy"}, "haproxy:3.0-alpine", online=False)
        self.assertEqual(rows[0]["available"], "unchecked")
        registry.assert_not_called()

    def test_digest_pin_uses_declared_tracking_channel_for_human_display(self):
        component = upgrade.Component(
            stack="stack2", name="firecrawl", service=None, container="firecrawl-api",
            compose=None, upstream="firecrawl/firecrawl", selectable=False,
        )
        record = {
            "stack":"stack2", "id":"firecrawl",
            "registry_source":"ghcr.io/firecrawl/firecrawl:latest",
        }
        state = container_registry.RegistryState(
            "ghcr.io/firecrawl/firecrawl@sha256:old", "sha256:old", "sha256:new",
            tracking_image="ghcr.io/firecrawl/firecrawl:latest", remote_status="ok",
        )
        rows, registry = self._inventory(
            component, record, "ghcr.io/firecrawl/firecrawl@sha256:old", registry_state=state,
        )
        self.assertEqual(rows[0]["current_display"], "latest (pinned)")
        self.assertEqual(rows[0]["available"], "update")
        registry.assert_called_once_with(
            "firecrawl-api",
            "ghcr.io/firecrawl/firecrawl@sha256:old",
            tracking_image="ghcr.io/firecrawl/firecrawl:latest",
        )

    def test_inventory_reports_current_when_release_candidate_equals_current(self):
        component = upgrade.Component(
            stack="stack6", name="hermes", service=None, container=None,
            compose=None, upstream="NousResearch/hermes-agent", selectable=True,
        )
        records = {"stack6/hermes": {
            "stack": "stack6", "id": "hermes",
            "version_source": {"type": "github_release", "repo": "NousResearch/hermes-agent"},
        }}
        with mock.patch("commands.upgrade.load_catalog", return_value=[component]), \
             mock.patch("commands.upgrade.component_records", return_value=records), \
             mock.patch("commands.upgrade.read_env", return_value={}), \
             mock.patch("commands.upgrade.load_plan", return_value={"schema_version": 1, "selected": {}}), \
             mock.patch("commands.upgrade.running_image", return_value="nousresearch/hermes-agent:v2026.9.11"), \
             mock.patch("internal.version_sources._github_latest", return_value="v2026.9.11"), \
             mock.patch("commands.upgrade.container_registry.inspect") as registry:
            rows = upgrade.inventory(query_upstream=True)
        self.assertEqual(rows[0]["available"], "current")
        registry.assert_not_called()

    def test_inventory_preserves_new_release_candidate(self):
        component = upgrade.Component(
            stack="stack5", name="dockhand", service=None, container=None,
            compose=None, upstream="Finsys/dockhand", selectable=False,
        )
        records = {"stack5/dockhand": {
            "stack":"stack5", "id":"dockhand",
            "version_source":{"type":"github_release","repo":"Finsys/dockhand"},
        }}
        with mock.patch("commands.upgrade.load_catalog", return_value=[component]), \
             mock.patch("commands.upgrade.component_records", return_value=records), \
             mock.patch("commands.upgrade.read_env", return_value={}), \
             mock.patch("commands.upgrade.load_plan", return_value={"schema_version":1,"selected":{}}), \
             mock.patch("commands.upgrade.running_image", return_value="finsys/dockhand:v1.0.40"), \
             mock.patch("internal.version_sources._github_latest", return_value="v1.0.47"):
            rows = upgrade.inventory(query_upstream=True)
        self.assertEqual(rows[0]["available"], "v1.0.47")

    def test_local_component_is_not_queried_against_registry(self):
        component = upgrade.Component(
            stack="stack6", name="sandbox", service="hermes-sandbox", container="hermes-sandbox",
            compose="stack6_-_hermes/docker-compose.yml", upstream=None, selectable=False,
        )
        rows, registry = self._inventory(
            component, {"stack":"stack6","id":"sandbox","availability":"local"}, "hermes-sandbox:local"
        )
        self.assertEqual(rows[0]["available"], "local")
        registry.assert_not_called()


if __name__ == "__main__":
    unittest.main()
