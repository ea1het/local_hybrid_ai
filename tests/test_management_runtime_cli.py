# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Public CLI dispatch tests for selective stack runtime start/stop.

These tests ensure the numeric stack selector and global JSON flag reach the
runtime lifecycle implementation through ``./local-ai`` semantics. They also
protect rejection of internal stack names and manifest directories at the
public boundary; dependency and Compose behaviour remain runtime-lifecycle
concerns.
"""

from __future__ import annotations

import contextlib
import io
import unittest
from unittest import mock

from commands import cli


class ManagementRuntimeCliTests(unittest.TestCase):
    def test_start_dispatches_numeric_stack_selector_through_public_cli(self):
        with mock.patch("commands.cli.runtime_lifecycle.main", return_value=0) as runtime:
            rc = cli.main(["start", "7"])
        self.assertEqual(rc, 0)
        runtime.assert_called_once_with("start", "7", json_output=False)

    def test_internal_stack_name_is_rejected_at_public_boundary(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), mock.patch("commands.cli.runtime_lifecycle.main") as runtime:
            rc = cli.main(["stop", "stack7"])
        self.assertEqual(rc, 2)
        self.assertIn("STACK_SELECTOR_INVALID", stderr.getvalue())
        runtime.assert_not_called()

    def test_manifest_directory_is_rejected_at_public_boundary(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), mock.patch("commands.cli.runtime_lifecycle.main") as runtime:
            rc = cli.main(["stop", "stack7_-_open-webui"])
        self.assertEqual(rc, 2)
        self.assertIn("STACK_SELECTOR_INVALID", stderr.getvalue())
        runtime.assert_not_called()

    def test_json_flag_is_forwarded_to_runtime_contract(self):
        with mock.patch("commands.cli.runtime_lifecycle.main", return_value=0) as runtime:
            rc = cli.main(["--json", "start", "7"])
        self.assertEqual(rc, 0)
        runtime.assert_called_once_with("start", "7", json_output=True)


if __name__ == "__main__":
    unittest.main()
