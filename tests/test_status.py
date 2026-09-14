# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""State-model tests for Desired / Deployed / Actual / Drift semantics.

These tests keep guarded-upgrade history distinct from observed runtime and
configuration intent. They exercise mutable-tag registry resolution, fixed tags,
digest pins, pre-history deployment baselines, cross-command Actual consistency
and fail-closed drift reporting when registry identity cannot be proven.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from commands import status
from commands import upgrade
from commands import upgrade_registry


class StatusStateTests(unittest.TestCase):
    def test_deployed_version_comes_from_latest_success_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            platform = root / "platform"
            platform.mkdir(parents=True)
            events = [
                {"success": True, "upgraded": [{"stack": "stack6", "component": "hermes", "version": "v1"}]},
                {"success": False, "selected": [{"stack": "stack6", "component": "hermes", "version": "v2"}]},
                {"success": True, "upgraded": [{"stack": "stack6", "component": "hermes", "version": "v3"}]},
            ]
            (platform / "upgrade-history.jsonl").write_text(
                "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
            )
            deployed = status._deployed_versions(root)
        self.assertEqual(deployed["stack6/hermes"], "v3")

    def test_deployed_prefers_recorded_history(self):
        self.assertEqual(status._deployed("stack6/hermes", "v3", "v3", {"stack6/hermes": "v2"}), "v2")

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
            current_version="8.10.0-alpine3.23", available_version="8.10.1-alpine3.23",
            local_digest="sha256:old", remote_digest="sha256:new",
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

    def test_exact_desired_resolves_legacy_floating_runtime_without_advancing_intent(self):
        component = SimpleNamespace(stack="stack2", name="redis", container="firecrawl-redis")
        state = SimpleNamespace(
            current_version="8.10.0-alpine3.23", available_version="8.10.1-alpine3.23",
            local_digest="sha256:old", remote_digest="sha256:new",
        )
        with mock.patch("commands.status.upgrade.load_catalog", return_value=[component]), \
             mock.patch("commands.status.upgrade.read_env", return_value={}), \
             mock.patch("commands.status.upgrade.compose_image", return_value="redis:8.10.0-alpine3.23"), \
             mock.patch("commands.status.upgrade.running_image", return_value="redis:alpine"), \
             mock.patch("commands.status.upgrade_registry.inspect", return_value=state) as inspect_mock:
            rows = status.inventory(deployed_versions={})
        inspect_mock.assert_called_once_with("firecrawl-redis", "redis:alpine")
        self.assertEqual(rows[0]["desired"], "8.10.0-alpine3.23")
        self.assertEqual(rows[0]["deployed"], "8.10.0-alpine3.23")
        self.assertEqual(rows[0]["actual"], "8.10.0-alpine3.23")
        self.assertEqual(rows[0]["drift"], "no")

    def test_floating_tag_same_digest_is_proven_no_drift(self):
        component = SimpleNamespace(stack="stack2", name="redis", container="firecrawl-redis")
        state = SimpleNamespace(
            current_version="8.10.1-alpine3.23", available_version="8.10.1-alpine3.23",
            local_digest="sha256:same", remote_digest="sha256:same",
        )
        with mock.patch("commands.status.upgrade.load_catalog", return_value=[component]), \
             mock.patch("commands.status.upgrade.read_env", return_value={}), \
             mock.patch("commands.status.upgrade.compose_image", return_value="redis:alpine"), \
             mock.patch("commands.status.upgrade.running_image", return_value="redis:alpine"), \
             mock.patch("commands.status.upgrade_registry.inspect", return_value=state):
            rows = status.inventory(deployed_versions={})
        self.assertEqual(rows[0]["desired"], "8.10.1-alpine3.23")
        self.assertEqual(rows[0]["actual"], "8.10.1-alpine3.23")
        self.assertEqual(rows[0]["drift"], "no")

    def test_fixed_semantic_tag_does_not_require_registry_resolution_for_drift(self):
        component = SimpleNamespace(stack="stack7", name="open-webui", container="open-webui")
        with mock.patch("commands.status.upgrade.load_catalog", return_value=[component]), \
             mock.patch("commands.status.upgrade.read_env", return_value={}), \
             mock.patch("commands.status.upgrade.compose_image", return_value="ghcr.io/open-webui/open-webui:v0.11.3"), \
             mock.patch("commands.status.upgrade.running_image", return_value="ghcr.io/open-webui/open-webui:v0.11.3"), \
             mock.patch("commands.status.upgrade_registry.inspect") as inspect_mock:
            rows = status.inventory(deployed_versions={})
        inspect_mock.assert_not_called()
        self.assertEqual(rows[0]["desired"], "v0.11.3")
        self.assertEqual(rows[0]["actual"], "v0.11.3")
        self.assertEqual(rows[0]["drift"], "no")

    def test_digest_pins_compare_immutable_identity_without_registry_resolution(self):
        component = SimpleNamespace(stack="stack2", name="firecrawl", container="firecrawl-api")
        desired_image = "ghcr.io/firecrawl/firecrawl@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        actual_image = "ghcr.io/firecrawl/firecrawl@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        with mock.patch("commands.status.upgrade.load_catalog", return_value=[component]), \
             mock.patch("commands.status.upgrade.read_env", return_value={}), \
             mock.patch("commands.status.upgrade.compose_image", return_value=desired_image), \
             mock.patch("commands.status.upgrade.running_image", return_value=actual_image), \
             mock.patch("commands.status.upgrade_registry.inspect") as inspect_mock:
            rows = status.inventory(deployed_versions={})
        inspect_mock.assert_not_called()
        self.assertEqual(rows[0]["desired"], "sha256:aaaaaaaaaaaa")
        self.assertEqual(rows[0]["actual"], "sha256:bbbbbbbbbbbb")
        self.assertEqual(rows[0]["drift"], "yes")

    def test_status_and_upgrade_check_share_concrete_actual_for_floating_tag(self):
        component = SimpleNamespace(
            stack="stack2", name="redis", container="firecrawl-redis",
            compose="stack2_-_web/docker-compose.yml", service="redis", upstream=None, selectable=False,
        )
        state = upgrade_registry.RegistryState(
            image="redis:alpine", tracking_image="redis:alpine", registry="docker.io", repository="library/redis",
            local_digest="sha256:old", remote_digest="sha256:new", remote_status="ok", tags_status="ok",
            current_version="8.10.0-alpine3.23", available_version="8.10.1-alpine3.23",
        )
        record = {"availability": "registry", "default_policy": "major-series"}
        policy_state = {"effective_policy": "major-series", "selection_valid": None}
        with mock.patch("commands.status.upgrade.load_catalog", return_value=[component]), \
             mock.patch("commands.status.upgrade.read_env", return_value={}), \
             mock.patch("commands.status.upgrade.compose_image", return_value="redis:alpine"), \
             mock.patch("commands.status.upgrade.running_image", return_value="redis:alpine"), \
             mock.patch("commands.upgrade.load_catalog", return_value=[component]), \
             mock.patch("commands.upgrade.read_env", return_value={}), \
             mock.patch("commands.upgrade.load_plan", return_value={"schema_version": 1, "selected": {}}), \
             mock.patch("commands.upgrade.component_records", return_value={"stack2/redis": record}), \
             mock.patch("commands.upgrade.compose_image", return_value="redis:alpine"), \
             mock.patch("commands.upgrade.running_image", return_value="redis:alpine"), \
             mock.patch("commands.upgrade.upgrade_policy.selection_status", return_value=policy_state), \
             mock.patch("commands.upgrade_registry.inspect", return_value=state):
            status_row = status.inventory(deployed_versions={})[0]
            upgrade_row = upgrade.inventory(query_upstream=True)[0]
        self.assertEqual(status_row["actual"], "8.10.0-alpine3.23")
        self.assertEqual(upgrade_row["actual_display"], "8.10.0-alpine3.23")
        self.assertEqual(status_row["actual"], upgrade_row["actual_display"])

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
