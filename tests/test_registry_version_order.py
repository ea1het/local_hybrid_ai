# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Ordering tests for registry release and tracking-channel candidates.

These tests prevent discovery from advertising an older exact release as an
upgrade and ensure mutable numeric channels remain inside their declared series.
They protect candidate ordering only; compatibility policy is tested separately.
"""

from __future__ import annotations

import unittest

from commands import upgrade_registry as container_registry


class RegistryVersionOrderTests(unittest.TestCase):
    def test_exact_release_never_advertises_older_same_major_version(self):
        tags = (
            "v0.1.121",
            "v0.3.8",
            "v0.11.3",
        )
        self.assertEqual(
            container_registry._release_candidates(tags, "v0.11.3"),
            ["v0.11.3"],
        )

    def test_exact_release_keeps_newer_versions_and_drops_older_versions(self):
        tags = (
            "v0.3.8",
            "v0.11.3",
            "v0.11.4",
            "v0.12.0",
        )
        self.assertEqual(
            container_registry._release_candidates(tags, "v0.11.3"),
            ["v0.12.0", "v0.11.4", "v0.11.3"],
        )

    def test_channel_discovery_still_tracks_its_numeric_family(self):
        tags = (
            "3.0.26-alpine3.24",
            "3.0.27-alpine3.24",
            "3.1.0-alpine3.24",
        )
        self.assertEqual(
            container_registry._channel_candidates(tags, "3.0-alpine"),
            ["3.0.27-alpine3.24", "3.0.26-alpine3.24"],
        )


if __name__ == "__main__":
    unittest.main()
