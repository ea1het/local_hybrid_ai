# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Check the three MCP configurations without deploying containers."""

import shutil
import subprocess
import sys

import pytest

from .verify import ROOT, compose_checks


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker Compose CLI required")
def test_compose_and_bootstrap(tmp_path):
    compose_checks(tmp_path)


def test_bootstrap_preserves_existing_local_environment(tmp_path):
    stack = tmp_path / "stack"
    shutil.copytree(ROOT, stack, ignore=shutil.ignore_patterns(".env", "__pycache__"))
    central = tmp_path / ".env"
    central.write_text("BASE_PATH=/global\n")
    local = stack / ".env"
    local.write_text("BASE_PATH=/local\n")
    result = subprocess.run([sys.executable, "-B", str(stack / "00-bootstrap.py")],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert "will not overwrite" in result.stderr
    assert local.read_text() == "BASE_PATH=/local\n"
    assert central.read_text() == "BASE_PATH=/global\n"
    assert not local.is_symlink()


def test_missing_global_environment_is_not_created(tmp_path):
    stack = tmp_path / "stack"
    shutil.copytree(ROOT, stack, ignore=shutil.ignore_patterns(".env", "__pycache__"))
    result = subprocess.run([sys.executable, "-B", str(stack / "00-bootstrap.py")],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert not (tmp_path / ".env").exists()
    assert not (stack / ".env").is_symlink()
