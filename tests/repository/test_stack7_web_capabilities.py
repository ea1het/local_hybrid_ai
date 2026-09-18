#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Cross-stack contract tests for Stack7's optional Stack2 web capabilities.

These tests prove Stack7 declares search/extraction as optional capabilities,
points at Stack2-owned SearXNG/Firecrawl services without re-owning them, and that
the SearXNG provider exposes the JSON response format required by the consumer.
They protect capability wiring without turning Stack2 into a required dependency.
"""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STACK7 = ROOT / "stack7_-_open-webui"


class Stack7WebCapabilityTests(unittest.TestCase):
    def test_manifest_declares_stack2_as_optional_provider(self):
        manifest = json.loads((STACK7 / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["requires"], [0, 3])
        self.assertIn(2, manifest["optional"])
        self.assertEqual(
            set(manifest["optional_consumes"]),
            {"web.search", "web.extract"},
        )

    def test_compose_uses_stack2_services_without_owning_them(self):
        compose = (STACK7 / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn('WEB_SEARCH_ENGINE: "searxng"', compose)
        self.assertIn('WEB_LOADER_ENGINE: "firecrawl"', compose)
        self.assertIn('http://searxng:8080', compose)
        self.assertIn('http://firecrawl-api:3002', compose)
        self.assertNotIn("\n  searxng:\n", compose)
        self.assertNotIn("\n  firecrawl-api:\n", compose)

    def test_stack2_searxng_contract_enables_json(self):
        settings = (
            ROOT
            / "stack2_-_searxng_firecrawl"
            / "config"
            / "searxng"
            / "settings.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("- json", settings)


if __name__ == "__main__":
    unittest.main()
