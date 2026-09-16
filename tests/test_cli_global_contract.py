# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Cross-command contract for public local-ai automation flags and rendering."""
from __future__ import annotations
import io, json, unittest
from contextlib import redirect_stdout
from unittest import mock
from commands import cli, completion, render

class GlobalCliContractTests(unittest.TestCase):
    def test_global_flags_are_position_independent(self):
        cases=[
            (["--json","--yes","status"],["status","--json","--yes"]),
            (["--yes","doctor","--json"],["doctor","--yes","--json"]),
            (["--json","--yes","inventory","rescan"],["inventory","rescan","--yes","--json"]),
        ]
        for left,right in cases:
            with self.subTest(left=left):
                self.assertEqual(cli._extract_global_options(left),cli._extract_global_options(right))

    def test_every_completion_branch_exposes_global_flags(self):
        branches=[[""],["status",""],["doctor",""],["backup",""],["restore",""],["inventory",""],["start",""],["stop",""],["install",""],["upgrade",""] ,["completion",""]]
        for words in branches:
            with self.subTest(words=words):
                values=completion.complete(words)
                self.assertIn("--json",values)
                self.assertIn("--yes",values)

    def test_render_json_emits_only_json(self):
        out=io.StringIO()
        with redirect_stdout(out): render.render_json({"success":True,"value":7})
        self.assertEqual(json.loads(out.getvalue()),{"success":True,"value":7})

    def test_render_cli_supports_custom_banner_and_header(self):
        out=io.StringIO()
        with redirect_stdout(out): render.render_cli("body",header="STATUS",banner="LOCAL-AI")
        self.assertEqual(out.getvalue(),"LOCAL-AI\n\nSTATUS\n\nbody\n")

    def test_read_only_commands_accept_yes_as_noop(self):
        with mock.patch("commands.status.main",return_value=0) as status_main:
            self.assertEqual(cli.main(["status","--yes"]),0)
            status_main.assert_called_once_with(json_output=False)
        with mock.patch("commands.doctor.json_payload",return_value={"success":True,"checks":[]}), mock.patch("commands.render.render_cli"):
            self.assertEqual(cli.main(["doctor","--yes"]),0)

    def test_backup_yes_is_consumed_by_public_boundary(self):
        with mock.patch.object(cli,"_run_internal",return_value=0) as run:
            self.assertEqual(cli.main(["--yes","backup"]),0)
        self.assertNotIn("--yes",run.call_args.args[1])

if __name__=="__main__": unittest.main()
