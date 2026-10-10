# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Preparation generates private service identities without repeated Client IDs."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys

from .verify import CLIENT_ID, ROOT, SERVICES


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prepare_initializes_settings_without_bootstrap(tmp_path, monkeypatch):
    stack = tmp_path / "stack"
    shutil.copytree(ROOT, stack, ignore=shutil.ignore_patterns(".env", "__pycache__"))
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
                            "GOOGLE_OAUTH_CLIENT_SECRET": "",
                            "FASTMCP_SERVER_AUTH_GOOGLE_JWT_SIGNING_KEY": "x" * 64},
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
    assert len(set(before.values())) == 3
    for name, path in settings.items():
        assert "GOOGLE_OAUTH_CLIENT_ID=" not in path.read_text()
        assert path.stat().st_mode & 0o777 == 0o600
        assert (tmp_path / "data" / name / "attachments").is_dir()
    # Remove obsolete local ID copies while preserving generated signing keys.
    for path in settings.values():
        path.write_text(path.read_text() + "GOOGLE_OAUTH_CLIENT_ID=obsolete-local-value\n")
    prepare.main()
    assert all(path.read_bytes() == before[name] for name, path in settings.items())
    assert central.read_bytes() == original
