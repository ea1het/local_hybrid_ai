# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Contracts for side-effect-free Bash/Zsh completion."""

from __future__ import annotations

import contextlib
import io
import unittest
from unittest import mock

from commands import cli, completion


class CompletionTests(unittest.TestCase):
    def test_top_level_completion(self):
        values = completion.complete([""])
        self.assertIn("upgrade", values)
        self.assertIn("completion", values)
        self.assertEqual(completion.complete(["up"]), ["upgrade"])

    def test_stack_completion_is_manifest_driven(self):
        with mock.patch("commands.completion.install.all_manifests", return_value={0: {}, 2: {}, 7: {}}):
            self.assertEqual(completion.complete(["start", "stack"]), ["stack0", "stack2", "stack7"])

    def test_upgrade_components_are_manifest_driven(self):
        compiled = {
            "schema_version": 1,
            "stacks": [{"id": "stack2", "components": [{"id": "redis"}, {"id": "searxng"}]}],
        }
        with mock.patch("commands.completion.component_inventory.compile_upgrade_catalog", return_value=compiled), \
             mock.patch("commands.completion.install.all_manifests", return_value={2: {}}):
            self.assertEqual(completion.complete(["upgrade", "stack2", ""]), ["redis", "searxng"])
            self.assertEqual(completion.complete(["upgrade", "stack2", "r"]), ["redis"])

    def test_shell_scripts_delegate_to_private_endpoint(self):
        bash = completion.shell_script("bash")
        zsh = completion.shell_script("zsh")
        self.assertIn("__complete", bash)
        self.assertIn("complete -F", bash)
        self.assertIn("__complete", zsh)
        self.assertIn("compdef", zsh)

    def test_private_endpoint_fails_quiet(self):
        with mock.patch("commands.completion.complete", side_effect=RuntimeError("boom")):
            self.assertEqual(cli.main(["__complete", "upgrade", ""]), 0)

    def test_completion_command_emits_shell_adapter(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rc = cli.main(["completion", "bash"])
        self.assertEqual(rc, 0)
        self.assertIn("__complete", output.getvalue())


if __name__ == "__main__":
    unittest.main()
