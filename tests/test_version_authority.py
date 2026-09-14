# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from commands import upgrade, upgrade_adopt, upgrade_entry, upgrade_registry


class VersionAuthorityTests(unittest.TestCase):
    def test_generic_guarded_components_are_selectable(self):
        records = upgrade.component_records()
        for component_key in ("stack1/haproxy", "stack2/redis", "stack2/rabbitmq", "stack5/dockhand"):
            record = records[component_key]
            self.assertTrue(record.get("selectable", True), component_key)
            self.assertEqual(record["execution"], {"mode": "guarded", "blocked_by": None})
            self.assertEqual(record["apply"]["type"], "env-version")

    def test_catalog_no_longer_uses_tracked_compose_pin_as_block_reason(self):
        for component_key, record in upgrade.component_records().items():
            self.assertNotEqual(record["execution"].get("blocked_by"), "tracked-compose-pin", component_key)

    def test_compose_baselines_pin_pre_adoption_runtime_versions(self):
        root = Path(__file__).resolve().parents[1]
        stack1 = (root / "stack1_-_haproxy_web" / "docker-compose.yml").read_text(encoding="utf-8")
        stack2 = (root / "stack2_-_searxng_firecrawl" / "docker-compose.yml").read_text(encoding="utf-8")
        stack5 = (root / "stack5_-_dockhand" / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("${HAPROXY_VERSION:-3.0.26-alpine3.24}", stack1)
        self.assertIn("${FIRECRAWL_REDIS_VERSION:-8.10.0-alpine3.23}", stack2)
        self.assertIn("${FIRECRAWL_RABBITMQ_VERSION:-3.13.7-alpine}", stack2)
        self.assertIn("${DOCKHAND_REPOSITORY:-fnsys/dockhand}:${DOCKHAND_VERSION:-v1.0.40}", stack5)
        self.assertNotIn("image: haproxy:3.0-alpine", stack1)
        self.assertNotIn("image: redis:alpine", stack2)
        self.assertNotIn("image: rabbitmq:3-alpine", stack2)

    def test_dockhand_adoption_uses_non_conflicting_split_authority(self):
        self.assertEqual(
            upgrade_adopt.AUTHORITIES["stack5/dockhand"],
            {"type": "split", "image_key": "DOCKHAND_REPOSITORY", "version_key": "DOCKHAND_VERSION"},
        )

    def test_exact_split_identity_does_not_need_registry_lookup(self):
        component = upgrade.Component(
            stack="stack7",
            name="open-webui",
            service="open-webui",
            container="open-webui",
            compose=None,
            upstream=None,
        )
        with mock.patch("commands.upgrade_adopt.upgrade_registry.inspect") as inspect:
            repository, version = upgrade_adopt._split_identity(
                component,
                "ghcr.io/open-webui/open-webui:v0.11.3",
            )
        self.assertEqual(repository, "ghcr.io/open-webui/open-webui")
        self.assertEqual(version, "v0.11.3")
        inspect.assert_not_called()

    def test_tracking_split_identity_resolves_exact_running_version(self):
        component = upgrade.Component(
            stack="stack2",
            name="redis",
            service="firecrawl-redis",
            container="firecrawl-redis",
            compose=None,
            upstream=None,
        )
        state = upgrade_registry.RegistryState(
            image="redis:alpine",
            local_digest="sha256:aaa",
            remote_digest="sha256:bbb",
            current_version="8.10.0-alpine3.23",
            available_version="8.10.1-alpine3.23",
        )
        with mock.patch("commands.upgrade_adopt.upgrade_registry.inspect", return_value=state):
            repository, version = upgrade_adopt._split_identity(component, "redis:alpine")
        self.assertEqual(repository, "redis")
        self.assertEqual(version, "8.10.0-alpine3.23")

    def test_selection_baseline_resolves_historical_tracking_runtime(self):
        component = upgrade.Component(
            stack="stack2",
            name="redis",
            service="firecrawl-redis",
            container="firecrawl-redis",
            compose="stack2_-_searxng_firecrawl/docker-compose.yml",
            upstream="redis/redis",
        )
        state = upgrade_registry.RegistryState(
            image="redis:alpine",
            local_digest="sha256:aaa",
            remote_digest="sha256:bbb",
            current_version="8.10.0-alpine3.23",
            available_version="8.10.1-alpine3.23",
        )
        with mock.patch("commands.upgrade_entry.upgrade.running_image", return_value="redis:alpine"), \
             mock.patch("commands.upgrade_entry.upgrade_registry.inspect", return_value=state):
            current = upgrade_entry._current_runtime_version(component, {})
        self.assertEqual(current, "8.10.0-alpine3.23")

    def test_selection_baseline_fails_closed_to_literal_when_registry_resolution_fails(self):
        component = upgrade.Component(
            stack="stack2",
            name="redis",
            service="firecrawl-redis",
            container="firecrawl-redis",
            compose="stack2_-_searxng_firecrawl/docker-compose.yml",
            upstream="redis/redis",
        )
        with mock.patch("commands.upgrade_entry.upgrade.running_image", return_value="redis:alpine"), \
             mock.patch(
                 "commands.upgrade_entry.upgrade_registry.inspect",
                 side_effect=upgrade_registry.RegistryError("rate limited"),
             ):
            current = upgrade_entry._current_runtime_version(component, {})
        self.assertEqual(current, "alpine")

    def test_adoption_appends_missing_authority_without_rewriting_existing_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("SECRET=keep-me\n", encoding="utf-8")
            path.chmod(0o600)
            written = upgrade_adopt._apply_missing(
                path,
                {
                    "HAPROXY_IMAGE": "haproxy",
                    "HAPROXY_VERSION": "3.0.26-alpine3.24",
                },
            )
            text = path.read_text(encoding="utf-8")
            self.assertEqual(written, ["HAPROXY_IMAGE", "HAPROXY_VERSION"])
            self.assertIn("SECRET=keep-me\n", text)
            self.assertIn("HAPROXY_IMAGE=haproxy\n", text)
            self.assertIn("HAPROXY_VERSION=3.0.26-alpine3.24\n", text)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_adoption_conflict_fails_without_mutating_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            original = "FIRECRAWL_REDIS_VERSION=8.9.9-alpine\n"
            path.write_text(original, encoding="utf-8")
            with self.assertRaises(upgrade_adopt.AdoptionError) as ctx:
                upgrade_adopt._apply_missing(
                    path,
                    {"FIRECRAWL_REDIS_VERSION": "8.10.0-alpine3.23"},
                )
            self.assertEqual(ctx.exception.code, "UPGRADE_ADOPTION_CONFLICT")
            self.assertEqual(path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
