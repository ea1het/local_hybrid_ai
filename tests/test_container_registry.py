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

    def test_equal_digests_mean_current(self):
        state = container_registry.RegistryState("rabbitmq:3-alpine", "sha256:a", "sha256:a")
        self.assertFalse(state.update_available)

    def test_different_digests_mean_update_available(self):
        state = container_registry.RegistryState("rabbitmq:3-alpine", "sha256:a", "sha256:b")
        self.assertTrue(state.update_available)

    def test_missing_digest_is_unknown_not_update(self):
        state = container_registry.RegistryState("rabbitmq:3-alpine", None, "sha256:b")
        self.assertIsNone(state.update_available)

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
