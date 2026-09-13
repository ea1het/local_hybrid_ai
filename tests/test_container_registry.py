from __future__ import annotations

import unittest
from unittest import mock

from internal import container_registry


class ContainerRegistryTests(unittest.TestCase):
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

    def test_equal_digests_mean_current(self):
        state = container_registry.RegistryState("rabbitmq:3-alpine", "sha256:a", "sha256:a")
        self.assertFalse(state.update_available)

    def test_different_digests_mean_update_available(self):
        state = container_registry.RegistryState("rabbitmq:3-alpine", "sha256:a", "sha256:b")
        self.assertTrue(state.update_available)

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

    def test_remote_inspection_is_read_only(self):
        cp = mock.Mock(returncode=0, stdout='"sha256:remote"\n')
        with mock.patch("internal.container_registry.subprocess.run", return_value=cp) as run:
            self.assertEqual(container_registry.remote_digest("rabbitmq:3-alpine"), "sha256:remote")
        self.assertEqual(
            run.call_args.args[0],
            ["docker", "buildx", "imagetools", "inspect", "rabbitmq:3-alpine", "--format", "{{json .Manifest.Digest}}"],
        )


if __name__ == "__main__":
    unittest.main()
