# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Public CLI dispatch tests for selective stack runtime start/stop.

These tests ensure stack selectors and the global JSON flag reach the runtime
lifecycle implementation through ``./local-ai`` semantics. They protect the
management boundary itself; dependency and Compose behaviour are tested in the
runtime-lifecycle test module.
"""

from __future__ import annotations

import unittest
from unittest import mock

from commands import cli


class ManagementRuntimeCliTests(unittest.TestCase):
    def test_start_dispatches_stack_selector_through_public_cli(self):
        with mock.patch("commands.cli.runtime_lifecycle.main", return_value=0) as runtime:
            rc = cli.main(["start", "stack7"])
        self.assertEqual(rc, 0)
        runtime.assert_called_once_with("start", "stack7", json_output=False)

    def test_stop_dispatches_manifest_directory_through_public_cli(self):
        with mock.patch("commands.cli.runtime_lifecycle.main", return_value=0) as runtime:
            rc = cli.main(["stop", "stack7_-_open-webui"])
        self.assertEqual(rc, 0)
        runtime.assert_called_once_with("stop", "stack7_-_open-webui", json_output=False)

    def test_json_flag_is_forwarded_to_runtime_contract(self):
        with mock.patch("commands.cli.runtime_lifecycle.main", return_value=0) as runtime:
            rc = cli.main(["--json", "start", "7"])
        self.assertEqual(rc, 0)
        runtime.assert_called_once_with("start", "7", json_output=True)


if __name__ == "__main__":
    unittest.main()
