# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Protect the single-source invariant for container version discovery.

Upgrade inventory must derive version evidence from the registry/repository that
owns the configured image rather than lateral APIs or hand-maintained metadata.
These tests also cover offline behavior, local-only components and failure states
so unavailable registry evidence never becomes a fabricated current version.
Persistent discovery cache is disabled inside the synthetic inventory helper;
cache behavior itself is covered independently by the registry-cache suite.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from commands import upgrade
from commands import upgrade_registry as container_registry

ROOT = Path(__file__).resolve().parents[1]


class VersionSourceTests(unittest.TestCase):
    def _inventory_component(self):
        return upgrade.Component(
            stack="stack1", name="haproxy", service=None, container="haproxy",
            compose=None, upstream="haproxy/haproxy", selectable=False,
        )

    def _inventory(self, component, record, image, *, online=True, registry_state=None):
        records = {f"{component.stack}/{component.name}": record}
        patches = [
            mock.patch.dict("os.environ", {"LOCAL_AI_REGISTRY_CACHE_TTL_SECONDS": "0"}),
            mock.patch("commands.upgrade.load_catalog", return_value=[component]),
            mock.patch("commands.upgrade.component_records", return_value=records),
            mock.patch("commands.upgrade.read_env", return_value={}),
            mock.patch("commands.upgrade.load_plan", return_value={"schema_version": 1, "selected": {}}),
            mock.patch("commands.upgrade.running_image", return_value=image),
            mock.patch("commands.upgrade.upgrade_registry.inspect", return_value=registry_state),
        ]
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6] as registry:
            return upgrade.inventory(query_upstream=online), registry

    def test_catalog_uses_no_lateral_version_sources(self):
        catalog = json.loads((ROOT / "commands" / "upgrade-components.json").read_text(encoding="utf-8"))
        components = [component for stack in catalog["stacks"] for component in stack["components"]]
        self.assertFalse(any("version_source" in component for component in components))
        self.assertFalse(any("registry_source" in component for component in components))

    def test_inventory_reports_registry_human_version_update(self):
        component = self._inventory_component()
        state = container_registry.RegistryState(
            image="haproxy:3.0-alpine", local_digest="sha256:old", remote_digest="sha256:new",
            tracking_image="haproxy:3.0-alpine", remote_status="ok",
            current_version="3.0.18-alpine", available_version="3.0.19-alpine",
            tags_status="ok", registry="docker.io", repository="library/haproxy",
        )
        rows, _ = self._inventory(component, {"stack":"stack1","id":"haproxy"}, "haproxy:3.0-alpine", registry_state=state)
        self.assertEqual(rows[0]["current_display"], "3.0.18-alpine")
        self.assertEqual(rows[0]["available"], "3.0.19-alpine")
        self.assertTrue(rows[0]["registry"]["update_available"])
        self.assertEqual(rows[0]["registry"]["registry"], "docker.io")
        self.assertEqual(rows[0]["registry"]["repository"], "library/haproxy")

    def test_inventory_reports_current_for_equal_registry_version(self):
        component = self._inventory_component()
        state = container_registry.RegistryState(
            image="haproxy:3.0-alpine", local_digest="sha256:same", remote_digest="sha256:same",
            tracking_image="haproxy:3.0-alpine", remote_status="ok",
            current_version="3.0.19-alpine", available_version="3.0.19-alpine", tags_status="ok",
        )
        rows, _ = self._inventory(component, {"stack":"stack1","id":"haproxy"}, "haproxy:3.0-alpine", registry_state=state)
        self.assertEqual(rows[0]["available"], "current")
        self.assertEqual(rows[0]["current_display"], "3.0.19-alpine")

    def test_inventory_reports_rate_limit_reason(self):
        component = self._inventory_component()
        state = container_registry.RegistryState(
            image="haproxy:3.0-alpine", local_digest="sha256:local", remote_digest=None,
            tracking_image="haproxy:3.0-alpine", remote_status="rate_limited", tags_status="rate_limited",
        )
        rows, _ = self._inventory(component, {"stack":"stack1","id":"haproxy"}, "haproxy:3.0-alpine", registry_state=state)
        self.assertEqual(rows[0]["available"], "unknown")
        self.assertEqual(rows[0]["registry"]["remote_status"], "rate_limited")
        self.assertEqual(upgrade._human_available(rows[0]), "unknown (rate limited)")

    def test_inventory_reports_unknown_when_registry_comparison_is_incomplete(self):
        component = self._inventory_component()
        state = container_registry.RegistryState(
            image="haproxy:3.0-alpine", local_digest=None, remote_digest="sha256:remote",
            tracking_image="haproxy:3.0-alpine", remote_status="ok", tags_status="ok",
        )
        rows, _ = self._inventory(component, {"stack":"stack1","id":"haproxy"}, "haproxy:3.0-alpine", registry_state=state)
        self.assertEqual(rows[0]["available"], "unknown")

    def test_inventory_offline_does_not_query_registry(self):
        component = self._inventory_component()
        rows, registry = self._inventory(component, {"stack":"stack1","id":"haproxy"}, "haproxy:3.0-alpine", online=False)
        self.assertEqual(rows[0]["available"], "unchecked")
        self.assertEqual(rows[0]["current_display"], "3.0-alpine")
        registry.assert_not_called()

    def test_digest_pin_uses_discovered_human_registry_version(self):
        component = upgrade.Component(
            stack="stack2", name="firecrawl", service=None, container="firecrawl-api",
            compose=None, upstream="firecrawl/firecrawl", selectable=False,
        )
        state = container_registry.RegistryState(
            image="ghcr.io/firecrawl/firecrawl@sha256:old", local_digest="sha256:old", remote_digest="sha256:new",
            current_version="2.11.300", available_version="2.11.331", remote_status="ok", tags_status="ok",
            registry="ghcr.io", repository="firecrawl/firecrawl",
        )
        rows, registry = self._inventory(component, {"stack":"stack2","id":"firecrawl"}, "ghcr.io/firecrawl/firecrawl@sha256:old", registry_state=state)
        self.assertEqual(rows[0]["current_display"], "2.11.300")
        self.assertEqual(rows[0]["available"], "2.11.331")
        registry.assert_called_once_with("firecrawl-api", "ghcr.io/firecrawl/firecrawl@sha256:old")

    def test_exact_tag_component_also_uses_its_image_registry(self):
        component = upgrade.Component(
            stack="stack7", name="open-webui", service=None, container="open-webui",
            compose=None, upstream="open-webui/open-webui", selectable=True,
        )
        state = container_registry.RegistryState(
            image="ghcr.io/open-webui/open-webui:v0.11.3", local_digest="sha256:old", remote_digest="sha256:new",
            current_version="v0.11.3", available_version="v0.11.4", remote_status="ok", tags_status="ok",
            registry="ghcr.io", repository="open-webui/open-webui",
        )
        rows, registry = self._inventory(component, {"stack":"stack7","id":"open-webui"}, "ghcr.io/open-webui/open-webui:v0.11.3", registry_state=state)
        self.assertEqual(rows[0]["current_display"], "v0.11.3")
        self.assertEqual(rows[0]["available"], "v0.11.4")
        registry.assert_called_once_with("open-webui", "ghcr.io/open-webui/open-webui:v0.11.3")

    def test_local_component_is_not_queried_against_registry(self):
        component = upgrade.Component(
            stack="stack6", name="sandbox", service="hermes-sandbox", container="hermes-sandbox",
            compose="stack6_-_hermes/docker-compose.yml", upstream=None, selectable=False,
        )
        rows, registry = self._inventory(component, {"stack":"stack6","id":"sandbox","availability":"local"}, "hermes-sandbox:local")
        self.assertEqual(rows[0]["available"], "local")
        registry.assert_not_called()


if __name__ == "__main__":
    unittest.main()
