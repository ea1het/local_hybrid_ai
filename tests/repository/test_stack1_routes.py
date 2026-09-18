# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Configuration-contract tests for Stack1 published routes and landing links.

The tests keep HAProxy, the static index and environment-template naming aligned
for the Open WebUI and NorAI/Hermes routes. They specifically prevent the retired
Agentia route vocabulary from reappearing in active sources and verify the public
origin expected by Hermes CORS configuration.
"""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STACK1 = ROOT / "stack1_-_haproxy_web"


class Stack1RouteContractTests(unittest.TestCase):
    def test_root_index_exposes_open_webui_and_norai(self):
        html = (STACK1 / "config" / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="https://chat.casa.lan"', html)
        self.assertIn("Open WebUI", html)
        self.assertIn('href="https://norai.casa.lan"', html)
        self.assertIn("NorAI", html)

    def test_norai_route_contract_replaces_agentia_in_active_sources(self):
        paths = (
            ROOT / ".env.template",
            STACK1 / "01-prepare.sh",
            STACK1 / "docker-compose.yml",
            STACK1 / "config" / "haproxy" / "haproxy.cfg",
            STACK1 / "config" / "web" / "index.html",
        )
        combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)
        self.assertIn("NORAI_HOSTNAME", combined)
        self.assertIn("NORAI_TARGET", combined)
        self.assertNotIn("AGENTIA_", combined)
        self.assertNotIn("agentia", combined.lower())

    def test_norai_haproxy_route_is_complete(self):
        config = (STACK1 / "config" / "haproxy" / "haproxy.cfg").read_text(encoding="utf-8")
        self.assertIn('acl is_norai   hdr(host) -i "${NORAI_HOSTNAME}.${ROOT_HOSTNAME}"', config)
        self.assertIn("use_backend be_norai   if is_norai", config)
        self.assertIn("backend be_norai", config)
        self.assertIn('server hermes "${NORAI_TARGET}"', config)

    def test_norai_public_origin_is_documented_for_hermes(self):
        env_template = (ROOT / ".env.template").read_text(encoding="utf-8")
        self.assertIn("NORAI_HOSTNAME=norai", env_template)
        self.assertIn("NORAI_TARGET=hermes:9119", env_template)
        self.assertIn("API_SERVER_CORS_ORIGINS=https://norai.casa.lan", env_template)


if __name__ == "__main__":
    unittest.main()
