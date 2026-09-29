# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Test the Stack 70 wrapper without issuing credentials or starting services.

These tests load the Python CLI entrypoint and replace its subprocess
calls. They verify lock safety, bootstrap-before-prepare ordering, failure
handling, and manual-only startup instructions.
"""

import importlib.machinery
import importlib.util
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True

import pytest

from tests.helpers import ROOT


def load_wrapper():
    """Load the Stack 70 CLI without executing its main function."""
    path = ROOT / "wrapper/bin/stack-70.py"
    loader = importlib.machinery.SourceFileLoader("stack_70_wrapper_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_existing_lock_skips_bootstrap_and_prepare(tmp_path, monkeypatch, capsys):
    """Leave credentials untouched when preparation was already recorded."""
    wrapper = load_wrapper()
    lock = tmp_path / ".lock"
    lock.write_text("prepared")
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run"))

    assert wrapper.main(["install"]) == 0
    output = capsys.readouterr().out
    assert "bootstrap and prepare were not run" in output
    assert "Removing .lock manually" in output
    assert "\n\nStack 70 is PREPARED" in output
    assert "docker compose --env-file .env -f docker-compose.yml up -d --build" in output


def test_fresh_stack_bootstraps_then_prepares(tmp_path, monkeypatch, capsys):
    """Call only the two package modules with closed stdin and validate the lock."""
    wrapper = load_wrapper()
    lock = tmp_path / ".lock"
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    calls = []

    def fake_run(command, **kwargs):
        """Record calls and simulate a successful preparation lock."""
        calls.append((command, kwargs))
        if command[-1] == wrapper.PREPARE_MODULE:
            lock.write_text("prepared")
        return SimpleNamespace(returncode=0, stdout="audit passed\n", stderr="")

    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)
    assert wrapper.main(["install"]) == 0
    assert [call[0] for call in calls] == [
        [sys.executable, "-B", "-m", wrapper.BOOTSTRAP_MODULE],
        [sys.executable, "-B", "-m", wrapper.PREPARE_MODULE],
    ]
    assert all(options["stdin"] == wrapper.subprocess.DEVNULL for _, options in calls)
    assert all(options["cwd"] == tmp_path for _, options in calls)
    assert str(ROOT) in calls[0][1]["env"]["PYTHONPATH"].split(wrapper.os.pathsep)
    assert "audit passed\n\nStack 70 is PREPARED" in capsys.readouterr().out


@pytest.mark.parametrize("failed_module", ["bootstrap", "prepare"])
def test_failure_stops_without_startup_guidance(tmp_path, monkeypatch, capsys, failed_module):
    """Propagate a failed phase and never claim that preparation completed."""
    wrapper = load_wrapper()
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", tmp_path / ".lock")
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    calls = []

    def fake_run(command, **kwargs):
        """Fail at the selected package module and record invocation order."""
        calls.append(command[-1])
        failed = (failed_module == "bootstrap" and command[-1] == wrapper.BOOTSTRAP_MODULE) or (
            failed_module == "prepare" and command[-1] == wrapper.PREPARE_MODULE
        )
        return SimpleNamespace(returncode=7 if failed else 0, stdout="", stderr="audit failed\n" if failed else "")

    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)
    assert wrapper.main(["install"]) == 7
    assert len(calls) == (1 if failed_module == "bootstrap" else 2)
    captured = capsys.readouterr()
    assert "audit failed" in captured.err
    assert "docker compose" not in captured.out


def test_symlink_lock_is_rejected(tmp_path, monkeypatch):
    """Reject a redirected lock before invoking either module."""
    wrapper = load_wrapper()
    target = tmp_path / "target"
    target.write_text("prepared")
    lock = tmp_path / ".lock"
    lock.symlink_to(target)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run"))

    assert wrapper.main(["install"]) == 1
