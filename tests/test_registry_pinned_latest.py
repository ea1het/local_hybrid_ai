# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Protect registry discovery for digest-pinned images whose package exposes only a mutable latest channel.

These tests cover the conservative mapping between immutable local digests, the
registry's latest manifest and publication-time evidence. They specifically guard
against falsely advertising an older digest as an upgrade and against turning
missing publication metadata into a confident current/update decision.
"""

from __future__ import annotations

import unittest
from unittest import mock

from commands import upgrade_registry as container_registry


class RegistryPinnedLatestTests(unittest.TestCase):
    def test_digest_label_uses_first_nine_sha_characters(self):
        self.assertEqual(
            container_registry.digest_label("sha256:df1a393ce8bfc3801570"),
            "latest(df1a393ce)",
        )

    def test_digest_only_latest_only_package_reports_current_with_digest_label(self):
        image = "ghcr.io/firecrawl/playwright-service@sha256:same111111"
        tags = container_registry.TagProbe(("latest", "linux-amd64", "linux-arm64"), "ok")

        def manifest(ref: str):
            if ref.endswith(":latest"):
                return container_registry.RemoteProbe("sha256:same111111", "ok")
            return container_registry.RemoteProbe(None, "not_found")

        with mock.patch("commands.upgrade_registry.local_digest", return_value="sha256:same111111"), \
             mock.patch("commands.upgrade_registry.local_version_hint", return_value=None), \
             mock.patch("commands.upgrade_registry.registry_tags", return_value=tags), \
             mock.patch("commands.upgrade_registry.manifest_probe", side_effect=manifest):
            state = container_registry.inspect("firecrawl-playwright", image)

        self.assertEqual(state.current_version, "latest(same11111)")
        self.assertEqual(state.available_version, "latest(same11111)")
        self.assertEqual(state.tracking_image, "ghcr.io/firecrawl/playwright-service:latest")
        self.assertEqual(state.remote_digest, "sha256:same111111")
        self.assertTrue(state.latest_only)
        self.assertFalse(state.update_available)

    def test_digest_only_latest_only_package_reports_newer_digest_by_publication_time(self):
        image = "ghcr.io/firecrawl/nuq-postgres@sha256:old111111111"
        tags = container_registry.TagProbe(("latest", "linux-amd64", "linux-arm64"), "ok")

        publications = {
            "ghcr.io/firecrawl/nuq-postgres@sha256:old111111111": container_registry.PublicationProbe(
                "sha256:old111111111", "ok", "2026-09-01T10:00:00Z"
            ),
            "ghcr.io/firecrawl/nuq-postgres:latest": container_registry.PublicationProbe(
                "sha256:new222222222", "ok", "2026-09-12T10:00:00Z"
            ),
        }

        with mock.patch("commands.upgrade_registry.local_digest", return_value="sha256:old111111111"), \
             mock.patch("commands.upgrade_registry.local_version_hint", return_value=None), \
             mock.patch("commands.upgrade_registry.registry_tags", return_value=tags), \
             mock.patch(
                 "commands.upgrade_registry.manifest_probe",
                 return_value=container_registry.RemoteProbe("sha256:new222222222", "ok"),
             ), \
             mock.patch(
                 "commands.upgrade_registry.manifest_publication",
                 side_effect=lambda ref: publications[ref],
             ):
            state = container_registry.inspect("firecrawl-postgres", image)

        self.assertEqual(state.current_version, "latest(old111111)")
        self.assertEqual(state.available_version, "latest(new222222)")
        self.assertEqual(state.local_published_at, "2026-09-01T10:00:00Z")
        self.assertEqual(state.remote_published_at, "2026-09-12T10:00:00Z")
        self.assertTrue(state.update_available)

    def test_digest_only_latest_only_package_rejects_older_remote_digest(self):
        image = "ghcr.io/firecrawl/nuq-postgres@sha256:new222222222"
        tags = container_registry.TagProbe(("latest", "linux-amd64"), "ok")

        publications = {
            "ghcr.io/firecrawl/nuq-postgres@sha256:new222222222": container_registry.PublicationProbe(
                "sha256:new222222222", "ok", "2026-09-12T10:00:00Z"
            ),
            "ghcr.io/firecrawl/nuq-postgres:latest": container_registry.PublicationProbe(
                "sha256:old111111111", "ok", "2026-09-01T10:00:00Z"
            ),
        }

        with mock.patch("commands.upgrade_registry.local_digest", return_value="sha256:new222222222"), \
             mock.patch("commands.upgrade_registry.local_version_hint", return_value=None), \
             mock.patch("commands.upgrade_registry.registry_tags", return_value=tags), \
             mock.patch(
                 "commands.upgrade_registry.manifest_probe",
                 return_value=container_registry.RemoteProbe("sha256:old111111111", "ok"),
             ), \
             mock.patch(
                 "commands.upgrade_registry.manifest_publication",
                 side_effect=lambda ref: publications[ref],
             ):
            state = container_registry.inspect("firecrawl-postgres", image)

        self.assertEqual(state.available_version, "latest(new222222)")
        self.assertFalse(state.update_available)

    def test_digest_only_latest_only_package_fails_closed_without_dates(self):
        image = "ghcr.io/firecrawl/nuq-postgres@sha256:old111111111"
        tags = container_registry.TagProbe(("latest", "linux-amd64"), "ok")

        with mock.patch("commands.upgrade_registry.local_digest", return_value="sha256:old111111111"), \
             mock.patch("commands.upgrade_registry.local_version_hint", return_value=None), \
             mock.patch("commands.upgrade_registry.registry_tags", return_value=tags), \
             mock.patch(
                 "commands.upgrade_registry.manifest_probe",
                 return_value=container_registry.RemoteProbe("sha256:new222222222", "ok"),
             ), \
             mock.patch(
                 "commands.upgrade_registry.manifest_publication",
                 return_value=container_registry.PublicationProbe(None, "ok", None),
             ):
            state = container_registry.inspect("firecrawl-postgres", image)

        self.assertEqual(state.current_version, "latest(old111111)")
        self.assertIsNone(state.available_version)
        self.assertIsNone(state.update_available)

    def test_manifest_publication_prefers_registry_last_modified(self):
        headers = {
            "Docker-Content-Digest": "sha256:abc",
            "Last-Modified": "Sat, 12 Sep 2026 10:00:00 GMT",
        }
        with mock.patch(
            "commands.upgrade_registry._registry_request",
            return_value=(200, headers, b"{}"),
        ):
            probe = container_registry.manifest_publication(
                "ghcr.io/firecrawl/playwright-service:latest"
            )
        self.assertEqual(probe.digest, "sha256:abc")
        self.assertEqual(probe.status, "ok")
        self.assertEqual(probe.published_at, "2026-09-12T10:00:00Z")

    def test_semantic_digest_package_does_not_collapse_to_latest_channel(self):
        image = "ghcr.io/firecrawl/firecrawl@sha256:old"
        tags = container_registry.TagProbe(("2.11.332", "2.11.310", "latest"), "ok")

        def manifest(ref: str):
            if ref.endswith(":2.11.332"):
                return container_registry.RemoteProbe("sha256:new", "ok")
            if ref.endswith(":2.11.310"):
                return container_registry.RemoteProbe("sha256:old", "ok")
            return container_registry.RemoteProbe("sha256:new", "ok")

        with mock.patch("commands.upgrade_registry.local_digest", return_value="sha256:old"), \
             mock.patch("commands.upgrade_registry.local_version_hint", return_value=None), \
             mock.patch("commands.upgrade_registry.registry_tags", return_value=tags), \
             mock.patch("commands.upgrade_registry.manifest_probe", side_effect=manifest):
            state = container_registry.inspect("firecrawl-api", image)

        self.assertEqual(state.current_version, "2.11.310")
        self.assertEqual(state.available_version, "2.11.332")
        self.assertTrue(state.update_available)


if __name__ == "__main__":
    unittest.main()
