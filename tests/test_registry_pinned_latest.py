from __future__ import annotations

import unittest
from unittest import mock

from internal import container_registry


class RegistryPinnedLatestTests(unittest.TestCase):
    def test_digest_only_latest_only_package_reports_current_by_digest(self):
        image = "ghcr.io/firecrawl/playwright-service@sha256:same"
        tags = container_registry.TagProbe(("latest", "linux-amd64", "linux-arm64"), "ok")

        def manifest(ref: str):
            if ref.endswith(":latest"):
                return container_registry.RemoteProbe("sha256:same", "ok")
            return container_registry.RemoteProbe(None, "not_found")

        with mock.patch("internal.container_registry.local_digest", return_value="sha256:same"), \
             mock.patch("internal.container_registry.local_version_hint", return_value=None), \
             mock.patch("internal.container_registry.registry_tags", return_value=tags), \
             mock.patch("internal.container_registry.manifest_probe", side_effect=manifest):
            state = container_registry.inspect("firecrawl-playwright", image)

        self.assertIsNone(state.current_version)
        self.assertIsNone(state.available_version)
        self.assertEqual(state.tracking_image, "ghcr.io/firecrawl/playwright-service:latest")
        self.assertEqual(state.remote_digest, "sha256:same")
        self.assertFalse(state.update_available)
        self.assertEqual(container_registry.display_label(image), "pinned")

    def test_digest_only_latest_only_package_reports_update_by_digest(self):
        image = "ghcr.io/firecrawl/nuq-postgres@sha256:old"
        tags = container_registry.TagProbe(("latest", "linux-amd64", "linux-arm64"), "ok")

        with mock.patch("internal.container_registry.local_digest", return_value="sha256:old"), \
             mock.patch("internal.container_registry.local_version_hint", return_value=None), \
             mock.patch("internal.container_registry.registry_tags", return_value=tags), \
             mock.patch(
                 "internal.container_registry.manifest_probe",
                 return_value=container_registry.RemoteProbe("sha256:new", "ok"),
             ):
            state = container_registry.inspect("firecrawl-postgres", image)

        self.assertIsNone(state.current_version)
        self.assertIsNone(state.available_version)
        self.assertEqual(state.tracking_image, "ghcr.io/firecrawl/nuq-postgres:latest")
        self.assertTrue(state.update_available)

    def test_semantic_digest_package_does_not_collapse_to_latest_channel(self):
        image = "ghcr.io/firecrawl/firecrawl@sha256:old"
        tags = container_registry.TagProbe(("2.11.332", "2.11.310", "latest"), "ok")

        def manifest(ref: str):
            if ref.endswith(":2.11.332"):
                return container_registry.RemoteProbe("sha256:new", "ok")
            if ref.endswith(":2.11.310"):
                return container_registry.RemoteProbe("sha256:old", "ok")
            return container_registry.RemoteProbe("sha256:new", "ok")

        with mock.patch("internal.container_registry.local_digest", return_value="sha256:old"), \
             mock.patch("internal.container_registry.local_version_hint", return_value=None), \
             mock.patch("internal.container_registry.registry_tags", return_value=tags), \
             mock.patch("internal.container_registry.manifest_probe", side_effect=manifest):
            state = container_registry.inspect("firecrawl-api", image)

        self.assertEqual(state.current_version, "2.11.310")
        self.assertEqual(state.available_version, "2.11.332")
        self.assertTrue(state.update_available)


if __name__ == "__main__":
    unittest.main()
