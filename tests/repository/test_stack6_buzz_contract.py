#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Protect reproducible Stack6 Buzz CLI provisioning and runtime compatibility.

The contract pins Buzz source to an immutable upstream commit, builds the upstream
CLI package, stores the binary in installation-owned Hermes data and validates it
inside the exact Hermes image with a constrained disposable container. These tests
ensure provisioning remains reproducible rather than drifting with upstream main.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STACK6 = ROOT / "stack6_-_hermes"
LIFECYCLE = ROOT / "src" / "local_ai_cli" / "install-lifecycle.json"


class Stack6BuzzContractTests(unittest.TestCase):
    def test_stack6_prepare_provisions_buzz_after_base_prepare(self) -> None:
        lifecycle = json.loads(LIFECYCLE.read_text(encoding="utf-8"))
        prepare = lifecycle["stacks"]["6"]["prepare"]
        self.assertEqual(prepare[:2], [["./01-prepare.sh"], ["bash", "./03-buzz.sh"]])

    def test_compose_defaults_buzz_cli_to_managed_runtime_path(self) -> None:
        compose = (STACK6 / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("BUZZ_CLI_PATH: ${BUZZ_CLI_PATH:-/opt/data/bin/buzz}", compose)
        self.assertIn("${BASE_PATH}/${HERMES_SERVICE}/data:/opt/data", compose)

    def test_buzz_source_is_immutable_and_build_uses_upstream_cli_package(self) -> None:
        script = (STACK6 / "03-buzz.sh").read_text(encoding="utf-8")
        dockerfile = (STACK6 / "config" / "buzz" / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn('BUZZ_SOURCE_REPOSITORY="https://github.com/block/buzz.git"', script)
        self.assertRegex(script, r'BUZZ_SOURCE_REF="[0-9a-f]{40}"')
        self.assertIn('BUZZ_EXPECTED_CONTAINER_PATH="/opt/data/bin/buzz"', script)
        self.assertIn("git checkout --detach FETCH_HEAD", dockerfile)
        self.assertIn('test "$(git rev-parse HEAD)" = "${BUZZ_SOURCE_REF}"', dockerfile)
        self.assertIn("cargo build --locked --release -p buzz-cli", dockerfile)

    def test_buzz_binary_is_validated_inside_exact_hermes_image(self) -> None:
        script = (STACK6 / "03-buzz.sh").read_text(encoding="utf-8")
        self.assertIn('"${HERMES_IMAGE}:${HERMES_VERSION}"', script)
        self.assertIn('--entrypoint "${container_path}"', script)
        self.assertIn("--network none", script)
        self.assertIn("--read-only", script)


if __name__ == "__main__":
    unittest.main()
