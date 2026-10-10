# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Preparation preserves local settings and keeps Google configuration central."""

import sys

sys.dont_write_bytecode = True

import importlib.util
import json
import os
import shutil
import subprocess

from .verify import CLIENT_ID, ROOT, SERVICES


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prepare_initializes_settings_without_bootstrap(tmp_path, monkeypatch):
    stack = tmp_path / "stack"
    shutil.copytree(ROOT, stack, ignore=shutil.ignore_patterns(".env", "__pycache__"))
    code_before = {path: (path.read_bytes(), path.stat().st_mode)
                   for path in stack.glob("*.py")}
    central = tmp_path / ".env"
    central.write_text(f"MCP_GOOGLE_OAUTH_CLIENT_ID={CLIENT_ID}\n")
    original = central.read_bytes()
    helper = load("stack80_test_env", stack / "stack_env.py")
    monkeypatch.setitem(sys.modules, "stack_env", helper)
    prepare = load("stack80_test_prepare", stack / "01-prepare.py")
    config = {
        "networks": {"redlocal": {"name": "redlocal"}},
        "services": {name: {
            "user": f"{os.getuid()}:{os.getgid()}",
            "environment": {"GOOGLE_OAUTH_CLIENT_ID": CLIENT_ID,
                            "GOOGLE_OAUTH_CLIENT_SECRET": "fixture-secret",
                            "USER_GOOGLE_EMAIL": "agent@example.com"},
            "volumes": [{"source": str(tmp_path / "data" / name)}],
        } for name in SERVICES},
    }
    monkeypatch.setattr(prepare, "configuration", lambda: config)
    monkeypatch.setattr(prepare.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args, 0, json.dumps([{"Driver": "bridge"}])))
    monkeypatch.setattr(sys, "argv", ["01-prepare.py"])
    prepare.main()
    assert (stack / ".env").is_symlink()
    settings = {name: stack / "config" / name / ".env" for name in SERVICES}
    before = {name: path.read_bytes() for name, path in settings.items()}
    assert len(before) == 3
    for name, path in settings.items():
        assert "GOOGLE_OAUTH_CLIENT_ID=" not in path.read_text()
        assert path.stat().st_mode & 0o777 == 0o600
        assert (tmp_path / "data" / name / "attachments").is_dir()
    # Remove obsolete OAuth identities and copies; retain unrelated settings.
    for path in settings.values():
        path.write_text(path.read_text() + "WORKSPACE_MCP_LOG_LEVEL=WARNING\n"
                        "# Generated locally by 01-prepare.py. This is NOT the Google client secret.\n"
                        "FASTMCP_SERVER_AUTH_GOOGLE_JWT_SIGNING_KEY=old-key\n"
                        "GOOGLE_OAUTH_CLIENT_ID=obsolete-local-value\n"
                        "GOOGLE_OAUTH_CLIENT_SECRET=obsolete-local-secret\n"
                        "USER_GOOGLE_EMAIL=obsolete@example.com\n")
    prepare.main()
    for name, path in settings.items():
        assert path.read_bytes() == before[name] + b"WORKSPACE_MCP_LOG_LEVEL=WARNING\n"
    migrated = {name: path.read_bytes() for name, path in settings.items()}
    prepare.main()
    assert all(path.read_bytes() == migrated[name] for name, path in settings.items())
    assert central.read_bytes() == original
    assert all((path.read_bytes(), path.stat().st_mode) == value for path, value in code_before.items())
    assert not list(stack.rglob("__pycache__"))
