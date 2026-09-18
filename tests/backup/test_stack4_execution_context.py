#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Protect runtime-derived Gitea execution context used by the Stack4 backup adapter.

The adapter must discover rootless/rootful user, working path and custom config
locations from the running container instead of hard-coding one Gitea layout.
These tests also ensure helper commands preserve an explicit runtime user and fail
closed when a usable configuration path cannot be proven.
"""

import json
import unittest
from unittest import mock

import stack4_backup


class Stack4ExecutionContextTests(unittest.TestCase):
    def completed(self, args, rc=0, stdout=b"", stderr=b""):
        return stack4_backup.subprocess.CompletedProcess(args, rc, stdout=stdout, stderr=stderr)

    def test_rootless_context_is_discovered_not_hardcoded(self):
        inspect_doc = [{
            "Config": {
                "Image": "docker.gitea.com/gitea:1.27.1-rootless",
                "User": "1000:1000",
                "WorkingDir": "/var/lib/gitea",
                "Env": ["GITEA_CUSTOM=/etc/gitea", "TZ=Europe/Madrid"],
            },
            "Mounts": [
                {"Destination": "/etc/gitea"},
                {"Destination": "/var/lib/gitea"},
            ],
        }]

        def fake_run(args):
            if args[:2] == ["docker", "inspect"]:
                return self.completed(args, stdout=json.dumps(inspect_doc).encode())
            if args[:3] == ["docker", "exec", "gitea"]:
                return self.completed(args, rc=0 if args[-1] == "/etc/gitea/app.ini" else 1)
            raise AssertionError(args)

        with mock.patch.object(stack4_backup, "run_command", side_effect=fake_run):
            ctx = stack4_backup.discover_gitea_execution_context()

        self.assertEqual(ctx.user, "1000:1000")
        self.assertEqual(ctx.work_path, "/var/lib/gitea")
        self.assertEqual(ctx.custom_path, "/etc/gitea")
        self.assertEqual(ctx.config_path, "/etc/gitea/app.ini")

    def test_rootful_context_uses_image_default_user_and_dynamic_paths(self):
        inspect_doc = [{
            "Config": {
                "Image": "docker.gitea.com/gitea:1.28",
                "User": "",
                "WorkingDir": "/data",
                "Env": ["GITEA_CUSTOM=/data/gitea"],
            },
            "Mounts": [{"Destination": "/data"}],
        }]

        def fake_run(args):
            if args[:2] == ["docker", "inspect"]:
                return self.completed(args, stdout=json.dumps(inspect_doc).encode())
            if args[:3] == ["docker", "exec", "gitea"]:
                return self.completed(args, rc=0 if args[-1] == "/data/gitea/conf/app.ini" else 1)
            raise AssertionError(args)

        with mock.patch.object(stack4_backup, "run_command", side_effect=fake_run):
            ctx = stack4_backup.discover_gitea_execution_context()

        self.assertIsNone(ctx.user)
        self.assertEqual(ctx.work_path, "/data")
        self.assertEqual(ctx.custom_path, "/data/gitea")
        self.assertEqual(ctx.config_path, "/data/gitea/conf/app.ini")

        command = stack4_backup.build_helper_create_command(
            ctx, "helper", "/tmp/gitea-state.zip"
        )
        self.assertNotIn("--user", command)
        self.assertIn("/data/gitea/conf/app.ini", command)
        self.assertNotIn("1000:1000", command)
        self.assertNotIn("/etc/gitea", command)

    def test_build_helper_preserves_explicit_runtime_user(self):
        ctx = stack4_backup.GiteaExecutionContext(
            image="gitea:test",
            user="1234:5678",
            work_path="/srv/gitea",
            custom_path="/srv/gitea/custom",
            config_path="/srv/gitea/custom/conf/app.ini",
        )
        command = stack4_backup.build_helper_create_command(
            ctx, "helper", "/tmp/gitea-state.zip"
        )
        user_index = command.index("--user")
        self.assertEqual(command[user_index + 1], "1234:5678")
        self.assertNotIn("1000:1000", command)

    def test_context_discovery_fails_closed_when_config_is_not_found(self):
        inspect_doc = [{
            "Config": {
                "Image": "gitea:test",
                "User": "",
                "WorkingDir": "",
                "Env": [],
            },
            "Mounts": [{"Destination": "/data"}],
        }]

        def fake_run(args):
            if args[:2] == ["docker", "inspect"]:
                return self.completed(args, stdout=json.dumps(inspect_doc).encode())
            if args[:3] == ["docker", "exec", "gitea"]:
                return self.completed(args, rc=1)
            raise AssertionError(args)

        with mock.patch.object(stack4_backup, "run_command", side_effect=fake_run):
            with self.assertRaises(stack4_backup.Stack4BackupError):
                stack4_backup.discover_gitea_execution_context()


if __name__ == "__main__":
    unittest.main()
