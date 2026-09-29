# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Verify stack wrapper verbs and their Docker Compose lifecycle boundaries.

Argument parsing runs in subprocesses; lifecycle tests load wrappers with
temporary files and mocked Compose calls. No real stack is started or stopped.
"""

import importlib.util
import subprocess
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True

import pytest

from tests.helpers import ROOT


def load_wrapper(number):
    """Load one Python wrapper without executing its CLI."""
    script = ROOT / "wrapper" / "bin" / f"stack-{number}.py"
    spec = importlib.util.spec_from_file_location(f"stack_{number}_lifecycle_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("number", ("00", "10", "20", "30", "40", "50", "60", "70"))
def test_install_is_required_subcommand(number):
    """Reject a missing or unknown verb and advertise supported commands."""
    script = ROOT / "wrapper" / "bin" / f"stack-{number}.py"
    help_result = subprocess.run([sys.executable, "-B", str(script), "--help"],
                                 capture_output=True, text=True, check=False)
    assert help_result.returncode == 0
    assert f"usage: ./local-ai stack-{number}" in help_result.stdout
    assert f"stack-{number}.py" not in help_result.stdout
    assert "install" in help_result.stdout
    assert "status" in help_result.stdout
    if number != "00":
        assert "start" in help_result.stdout
        assert "stop" in help_result.stdout
    else:
        assert "start" not in help_result.stdout
        assert "stop" not in help_result.stdout

    for arguments in ((), ("unknown",)):
        result = subprocess.run([sys.executable, "-B", str(script), *arguments],
                                capture_output=True, text=True, check=False)
        assert result.returncode == 2
        assert f"usage: ./local-ai stack-{number}" in result.stderr
        assert f"stack-{number}.py" not in result.stderr

    install_help = subprocess.run([sys.executable, "-B", str(script), "install", "--help"],
                                  capture_output=True, text=True, check=False)
    assert install_help.returncode == 0
    status_help = subprocess.run([sys.executable, "-B", str(script), "status", "--help"],
                                 capture_output=True, text=True, check=False)
    assert status_help.returncode == 0
    assert f"usage: ./local-ai stack-{number} status" in status_help.stdout
    assert "--deep" in status_help.stdout


@pytest.mark.parametrize("number", ("00", "10", "20", "30", "40", "50", "60", "70"))
def test_status_dispatches_read_only_reporter(number, monkeypatch):
    """Pass --deep to the appropriate reporter without invoking Compose here."""
    wrapper = load_wrapper(number)
    calls = []
    reporter = "report_platform_status" if number == "00" else "report_status"
    monkeypatch.setattr(wrapper, reporter, lambda *args, **kwargs: calls.append((args, kwargs)) or 0)

    assert wrapper.main(["status", "--deep"]) == 0
    assert calls[0][1] == {"deep": True}


STACK_NUMBERS = ("10", "20", "30", "40", "50", "60", "70")


@pytest.mark.parametrize("number", STACK_NUMBERS)
def test_start_and_stop_use_expected_compose_commands(number, tmp_path, monkeypatch, capsys):
    """Keep Compose scoped to the stack and use stop only for Dockhand."""
    wrapper = load_wrapper(number)
    root = tmp_path / "root"
    root.mkdir()
    stack_dir = root / "stack"
    stack_dir.mkdir()
    (root / ".env").write_text("NETWORK_NAME=redlocal\n")
    (stack_dir / ".env").symlink_to("../.env")
    (stack_dir / "docker-compose.yml").write_text("services: {}\n")
    lock = stack_dir / ".lock"
    lock.write_text("prepared")
    monkeypatch.setattr(wrapper, "STACK_DIR", stack_dir)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    calls = []

    def fake_run(command, **kwargs):
        """Record Compose arguments without touching Docker."""
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="compose output\n", stderr="")

    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)
    assert wrapper.main(["start"]) == 0
    expected = ["docker", "compose", "--env-file", ".env", "-f", "docker-compose.yml", "up", "-d"]
    if number == "60":
        expected.append("--build")
    assert calls[0][0] == expected
    assert calls[0][1]["cwd"] == stack_dir
    assert calls[0][1]["stdin"] == subprocess.DEVNULL
    assert "not been verified" in capsys.readouterr().out

    lock.unlink()
    assert wrapper.main(["stop"]) == 0
    assert calls[1][0] == ["docker", "compose", "--env-file", ".env", "-f", "docker-compose.yml",
                            "stop" if number == "50" else "down"]
    assert not lock.exists()


@pytest.mark.parametrize("number", STACK_NUMBERS)
def test_start_requires_lock_but_stop_does_not(number, tmp_path, monkeypatch, capsys):
    """Refuse an unprepared start while keeping stop available for recovery."""
    wrapper = load_wrapper(number)
    root = tmp_path / "root"
    root.mkdir()
    stack_dir = root / "stack"
    stack_dir.mkdir()
    (root / ".env").write_text("NETWORK_NAME=redlocal\n")
    (stack_dir / ".env").symlink_to("../.env")
    (stack_dir / "docker-compose.yml").write_text("services: {}\n")
    monkeypatch.setattr(wrapper, "STACK_DIR", stack_dir)
    monkeypatch.setattr(wrapper, "LOCK_FILE", stack_dir / ".lock")
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout="", stderr=""
    ))

    assert wrapper.main(["start"]) == 1
    assert "missing regular lock" in capsys.readouterr().err
    assert wrapper.main(["stop"]) == 0


@pytest.mark.parametrize("number", STACK_NUMBERS)
def test_compose_error_is_returned(number, tmp_path, monkeypatch, capsys):
    """Propagate Compose failure instead of claiming containers are running."""
    wrapper = load_wrapper(number)
    root = tmp_path / "root"
    root.mkdir()
    stack_dir = root / "stack"
    stack_dir.mkdir()
    (root / ".env").write_text("NETWORK_NAME=redlocal\n")
    (stack_dir / ".env").symlink_to("../.env")
    (stack_dir / "docker-compose.yml").write_text("services: {}\n")
    (stack_dir / ".lock").write_text("prepared")
    monkeypatch.setattr(wrapper, "STACK_DIR", stack_dir)
    monkeypatch.setattr(wrapper, "LOCK_FILE", stack_dir / ".lock")
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=9, stdout="", stderr="compose failed\n"
    ))

    assert wrapper.main(["start"]) == 9
    captured = capsys.readouterr()
    assert "compose failed" in captured.err
    assert "containers started" not in captured.out
