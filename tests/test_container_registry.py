from __future__ import annotations

import json
import unittest
from unittest import mock

from internal import container_registry


class ContainerRegistryTests(unittest.TestCase):
    def test_parse_reference_uses_docker_hub_for_unqualified_images(self):
        ref = container_registry.parse_reference("rabbitmq:3-alpine")
        self.assertEqual(ref.registry, "docker.io")
        self.assertEqual(ref.registry_host, "registry-1.docker.io")
        self.assertEqual(ref.repository, "library/rabbitmq")
        self.assertEqual(ref.tag, "3-alpine")
        self.assertIsNone(ref.digest)

    def test_parse_reference_preserves_ghcr_package_and_digest(self):
        ref = container_registry.parse_reference(
            "ghcr.io/firecrawl/firecrawl@sha256:1910ef"
        )
        self.assertEqual(ref.registry, "ghcr.io")
        self.assertEqual(ref.repository, "firecrawl/firecrawl")
        self.assertIsNone(ref.tag)
        self.assertEqual(ref.digest, "sha256:1910ef")

    def test_repo_digest_matches_tagged_image_repository(self):
        digest = container_registry._repo_digest_for_image(
            "rabbitmq:3-alpine",
            ["rabbitmq@sha256:abc", "redis@sha256:def"],
        )
        self.assertEqual(digest, "sha256:abc")

    def test_repo_digest_matches_docker_hub_library_form(self):
        digest = container_registry._repo_digest_for_image(
            "rabbitmq:3-alpine",
            ["docker.io/library/rabbitmq@sha256:abc"],
        )
        self.assertEqual(digest, "sha256:abc")

    def test_repo_digest_matches_explicit_docker_io_namespace(self):
        digest = container_registry._repo_digest_for_image(
            "docker.io/searxng/searxng:2026.9.5-c7f3080aa",
            ["searxng/searxng@sha256:55e1fa15"],
        )
        self.assertEqual(digest, "sha256:55e1fa15")

    def test_repository_name_normalizes_docker_hub_aliases(self):
        self.assertEqual(container_registry._repository_name("rabbitmq:3-alpine"), "library/rabbitmq")
        self.assertEqual(container_registry._repository_name("docker.io/library/rabbitmq:3-alpine"), "library/rabbitmq")
        self.assertEqual(container_registry._repository_name("index.docker.io/searxng/searxng:tag"), "searxng/searxng")

    def test_registry_state_prefers_human_versions_for_update_comparison(self):
        state = container_registry.RegistryState(
            image="ghcr.io/firecrawl/firecrawl@sha256:old",
            local_digest="sha256:old",
            remote_digest="sha256:new",
            current_version="2.11.300",
            available_version="2.11.331",
        )
        self.assertTrue(state.update_available)

    def test_registry_state_same_human_version_is_current(self):
        state = container_registry.RegistryState(
            image="ghcr.io/firecrawl/firecrawl@sha256:same",
            local_digest="sha256:same",
            remote_digest="sha256:same",
            current_version="2.11.331",
            available_version="2.11.331",
        )
        self.assertFalse(state.update_available)

    def test_missing_digest_is_unknown_not_update(self):
        state = container_registry.RegistryState("rabbitmq:3-alpine", None, "sha256:b")
        self.assertIsNone(state.update_available)

    def test_local_digest_follows_container_image_id(self):
        container = {"Image": "sha256:image-id"}
        image = {"RepoDigests": ["docker.io/library/rabbitmq@sha256:local"]}
        with mock.patch("internal.container_registry._inspect_json", side_effect=[container, image]) as inspect_json:
            digest = container_registry.local_digest("firecrawl-rabbitmq", "rabbitmq:3-alpine")
        self.assertEqual(digest, "sha256:local")
        self.assertEqual(inspect_json.call_args_list, [mock.call("firecrawl-rabbitmq"), mock.call("sha256:image-id")])

    def test_local_digest_does_not_use_container_repo_digests(self):
        container = {"Image": "sha256:image-id", "RepoDigests": ["rabbitmq@sha256:wrong"]}
        image = {"RepoDigests": ["rabbitmq@sha256:right"]}
        with mock.patch("internal.container_registry._inspect_json", side_effect=[container, image]):
            self.assertEqual(
                container_registry.local_digest("firecrawl-rabbitmq", "rabbitmq:3-alpine"),
                "sha256:right",
            )

    def test_local_version_hint_accepts_oci_version_label_from_same_package(self):
        image_data = {
            "RepoTags": [],
            "Config": {"Labels": {"org.opencontainers.image.version": "2.11.300"}},
        }
        with mock.patch("internal.container_registry._local_image_data", return_value=image_data):
            hint = container_registry.local_version_hint(
                "firecrawl-api",
                "ghcr.io/firecrawl/firecrawl@sha256:old",
                ("2.11.300", "2.11.331"),
            )
        self.assertEqual(hint, "2.11.300")

    def test_registry_tags_reads_same_registry_package(self):
        body = json.dumps({"name": "firecrawl/firecrawl", "tags": ["2.11.331", "latest"]}).encode()
        with mock.patch("internal.container_registry._registry_request", return_value=(200, {}, body)) as request:
            probe = container_registry.registry_tags("ghcr.io/firecrawl/firecrawl@sha256:abc")
        self.assertEqual(probe.status, "ok")
        self.assertEqual(probe.tags, ("2.11.331", "latest"))
        ref = request.call_args.args[0]
        self.assertEqual(ref.registry, "ghcr.io")
        self.assertEqual(ref.repository, "firecrawl/firecrawl")
        self.assertEqual(request.call_args.args[1], "/v2/firecrawl/firecrawl/tags/list?n=1000")

    def test_registry_tags_follows_registry_v2_pagination(self):
        page1 = json.dumps({"tags": ["v0.1.121"]}).encode()
        page2 = json.dumps({"tags": ["v0.11.3", "v0.11.4"]}).encode()
        responses = [
            (200, {"Link": '</v2/open-webui/open-webui/tags/list?n=1000&last=v0.1.121>; rel="next"'}, page1),
            (200, {}, page2),
        ]
        with mock.patch("internal.container_registry._registry_request", side_effect=responses) as request:
            probe = container_registry.registry_tags("ghcr.io/open-webui/open-webui:v0.11.3")
        self.assertEqual(probe.status, "ok")
        self.assertEqual(probe.tags, ("v0.1.121", "v0.11.3", "v0.11.4"))
        self.assertEqual(request.call_count, 2)

    def test_registry_tags_preserves_rate_limit(self):
        with mock.patch("internal.container_registry._registry_request", return_value=(429, {}, b"")):
            probe = container_registry.registry_tags("redis:alpine")
        self.assertEqual(probe.tags, ())
        self.assertEqual(probe.status, "rate_limited")

    def test_manifest_probe_uses_same_registry_and_returns_content_digest(self):
        headers = {"Docker-Content-Digest": "sha256:remote"}
        with mock.patch("internal.container_registry._registry_request", return_value=(200, headers, b"")) as request:
            probe = container_registry.manifest_probe("ghcr.io/firecrawl/firecrawl:2.11.331")
        self.assertEqual(probe, container_registry.RemoteProbe("sha256:remote", "ok"))
        ref = request.call_args.args[0]
        self.assertEqual(ref.registry, "ghcr.io")
        self.assertEqual(ref.repository, "firecrawl/firecrawl")
        self.assertIn("/manifests/2.11.331", request.call_args.args[1])

    def test_manifest_probe_classifies_rate_limit(self):
        with mock.patch("internal.container_registry._registry_request", return_value=(429, {}, b"")):
            probe = container_registry.remote_probe("redis:alpine")
        self.assertIsNone(probe.digest)
        self.assertEqual(probe.status, "rate_limited")

    def test_version_tags_prefer_full_plain_human_version(self):
        tags = [
            "latest",
            "2",
            "2.11",
            "2.11.331-production",
            "2.11.331",
            "sha-deadbeef-linux-amd64",
            "buildcache-linux-amd64",
        ]
        self.assertEqual(container_registry.version_tags(tags)[0], "2.11.331")

    def test_release_candidates_preserve_v_prefix_and_exclude_hotfix_variant(self):
        tags = ("1.0.40-ldap-hotfix", "v1.0.40", "v1.0.47", "v2.0.0")
        self.assertEqual(
            container_registry._release_candidates(tags, "v1.0.40"),
            ["v1.0.47", "v1.0.40"],
        )

    def test_release_candidates_exclude_older_versions_and_other_major_lines(self):
        tags = ("v0.1.121", "v0.11.3", "v0.11.4", "v1.0.0")
        self.assertEqual(
            container_registry._release_candidates(tags, "v0.11.3"),
            ["v0.11.4", "v0.11.3"],
        )

    def test_channel_detection_recognizes_major_minor_alpine_channel(self):
        tags = ("3.0-alpine", "3.0.18-alpine", "3.1.2-alpine")
        self.assertTrue(container_registry._is_channel_tag("3.0-alpine", tags))

    def test_major_minor_channel_does_not_fall_into_other_series(self):
        tags = ("2.6.10-alpine", "3.0-alpine", "3.0.18-alpine", "3.1.2-alpine")
        self.assertEqual(
            container_registry._channel_candidates(tags, "3.0-alpine"),
            ["3.0.18-alpine"],
        )

    def test_exact_postgres_version_is_not_channel_without_more_specific_tag(self):
        tags = ("17.10-alpine", "17.9-alpine", "18.0-alpine")
        self.assertFalse(container_registry._is_channel_tag("17.10-alpine", tags))

    def test_digest_match_can_search_beyond_old_eighty_probe_limit(self):
        candidates = [f"2.11.{value}" for value in range(600, 499, -1)]
        target = candidates[95]
        reference = container_registry.parse_reference("ghcr.io/firecrawl/firecrawl@sha256:old")

        def manifest(ref: str):
            return container_registry.RemoteProbe(
                "sha256:old" if ref.endswith(":" + target) else "sha256:other",
                "ok",
            )

        with mock.patch("internal.container_registry.manifest_probe", side_effect=manifest):
            tag, status = container_registry._best_tag_for_digest(reference, "sha256:old", candidates)
        self.assertEqual(status, "ok")
        self.assertEqual(tag, target)

    def test_digest_only_image_maps_digest_to_human_registry_tag(self):
        image = "ghcr.io/firecrawl/firecrawl@sha256:old"
        tags = container_registry.TagProbe(("2.11.331", "2.11.300", "latest"), "ok")

        def manifest(ref: str):
            if ref.endswith(":2.11.331"):
                return container_registry.RemoteProbe("sha256:new", "ok")
            if ref.endswith(":2.11.300"):
                return container_registry.RemoteProbe("sha256:old", "ok")
            return container_registry.RemoteProbe(None, "not_found")

        with mock.patch("internal.container_registry.local_digest", return_value="sha256:old"), \
             mock.patch("internal.container_registry.local_version_hint", return_value=None), \
             mock.patch("internal.container_registry.registry_tags", return_value=tags), \
             mock.patch("internal.container_registry.manifest_probe", side_effect=manifest):
            state = container_registry.inspect("firecrawl-api", image)

        self.assertEqual(state.current_version, "2.11.300")
        self.assertEqual(state.available_version, "2.11.331")
        self.assertTrue(state.update_available)
        self.assertEqual(state.registry, "ghcr.io")
        self.assertEqual(state.repository, "firecrawl/firecrawl")

    def test_exact_registry_tag_uses_same_family_and_major_for_available_version(self):
        image = "ghcr.io/open-webui/open-webui:v0.11.3"
        tags = container_registry.TagProbe(("v0.1.121", "v0.11.3", "v0.11.4", "v1.0.0"), "ok")
        with mock.patch("internal.container_registry.local_digest", return_value="sha256:old"), \
             mock.patch("internal.container_registry.registry_tags", return_value=tags), \
             mock.patch("internal.container_registry.manifest_probe", return_value=container_registry.RemoteProbe("sha256:new", "ok")):
            state = container_registry.inspect("open-webui", image)
        self.assertEqual(state.current_version, "v0.11.3")
        self.assertEqual(state.available_version, "v0.11.4")

    def test_tracking_reference_rejects_lateral_registry_or_repository(self):
        with self.assertRaises(container_registry.RegistryError):
            container_registry.tracking_reference(
                "ghcr.io/firecrawl/firecrawl@sha256:abc",
                "docker.io/firecrawl/firecrawl:latest",
            )

    def test_display_label_prefers_discovered_human_version(self):
        self.assertEqual(
            container_registry.display_label(
                "ghcr.io/firecrawl/firecrawl@sha256:abc",
                discovered_version="2.11.300",
            ),
            "2.11.300",
        )


if __name__ == "__main__":
    unittest.main()
