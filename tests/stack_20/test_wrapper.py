# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Check Stack 20 wrapper preparation without touching running services.

The wrapper is loaded as a Python entrypoint. Tests use
temporary locks and mocked subprocess calls to verify noninteractive package
invocation, safe lock behavior, and failure propagation without Docker.
"""

import importlib.machinery
import importlib.util
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True

import pytest

from tests.helpers import ROOT


def load_wrapper():
    """Load the Stack 20 wrapper without executing its CLI."""
    path = ROOT / "wrapper/bin/stack-20.py"
    loader = importlib.machinery.SourceFileLoader("stack_20_wrapper_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_existing_lock_reports_status_without_running_prepare(tmp_path, monkeypatch, capsys):
    """Leave a prepared stack untouched and print the manual start command."""
    wrapper = load_wrapper()
    lock = tmp_path / ".lock"
    lock.write_text("prepared")
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper, "configuration_error", lambda: None)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run"))

    assert wrapper.main(["install"]) == 0
    output = capsys.readouterr().out
    assert "Removing .lock manually" in output
    assert "./local-ai stack-20 start" in output


def test_missing_lock_runs_package_and_requires_new_lock(tmp_path, monkeypatch, capsys):
    """Invoke preparation as a package with closed stdin and validate its lock."""
    wrapper = load_wrapper()
    platform = tmp_path / "stack-00_-_platform"
    platform.mkdir()
    (platform / ".lock").touch()
    lock = tmp_path / ".lock"
    monkeypatch.setattr(wrapper, "ROOT", tmp_path)
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    calls = []

    def fake_run(command, **kwargs):
        """Simulate successful preparation while capturing subprocess options."""
        calls.append((command, kwargs))
        if command[-1] == wrapper.PREPARE_MODULE:
            lock.write_text("prepared")
        return SimpleNamespace(returncode=0, stdout="prepared\n", stderr="")

    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)
    assert wrapper.main(["install"]) == 0
    assert calls[0][0] == [sys.executable, "-B", str(platform / "00-bootstrap.py"), "--stack", "20"]
    command, options = calls[1]
    assert command == [sys.executable, "-B", "-m", wrapper.PREPARE_MODULE]
    assert options["stdin"] == wrapper.subprocess.DEVNULL
    assert options["cwd"] == tmp_path
    assert str(tmp_path) in options["env"]["PYTHONPATH"].split(wrapper.os.pathsep)
    assert "prepared\n" in capsys.readouterr().out


def test_failed_prepare_does_not_claim_ready(tmp_path, monkeypatch, capsys):
    """Preserve a nonzero exit code and withhold deployment instructions."""
    wrapper = load_wrapper()
    platform = tmp_path / "stack-00_-_platform"
    platform.mkdir()
    (platform / ".lock").touch()
    monkeypatch.setattr(wrapper, "ROOT", tmp_path)
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", tmp_path / ".lock")
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=3, stdout="", stderr="missing Stack 0\n"
    ))

    assert wrapper.main(["install"]) == 3
    captured = capsys.readouterr()
    assert "missing Stack 0" in captured.err
    assert "docker compose" not in captured.out


def test_missing_platform_lock_does_not_create_directories(tmp_path, monkeypatch):
    """Reject an unprepared platform before starting scoped bootstrap."""
    wrapper = load_wrapper()
    monkeypatch.setattr(wrapper, "ROOT", tmp_path)
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", tmp_path / ".lock")
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run"))

    assert wrapper.main(["install"]) == 1


def test_symlink_lock_is_rejected(tmp_path, monkeypatch):
    """Avoid calling preparation when .lock redirects to another file."""
    wrapper = load_wrapper()
    target = tmp_path / "target"
    target.write_text("prepared")
    lock = tmp_path / ".lock"
    lock.symlink_to(target)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run"))

    assert wrapper.main(["install"]) == 1


def test_managed_config_must_match_prepared_files(tmp_path, monkeypatch):
    """Detect an image-generated settings file or missing limiter file."""
    wrapper = load_wrapper()
    stack_dir = tmp_path / "stack-20_-_searxng_firecrawl"
    source_dir = stack_dir / "config/searxng"
    target_dir = tmp_path / "runtime/service_-_searxng/config"
    source_dir.mkdir(parents=True)
    target_dir.mkdir(parents=True)
    monkeypatch.setattr(wrapper, "STACK_DIR", stack_dir)
    monkeypatch.setattr(wrapper, "protected_text", lambda path: f"BASE_PATH={tmp_path / 'runtime'}\n")
    for name in ("settings.yml", "limiter.toml"):
        (source_dir / name).write_text("managed")
        (target_dir / name).write_text("managed")

    assert wrapper.configuration_error() is None
    (target_dir / "settings.yml").write_text("image-generated")
    assert "settings.yml" in wrapper.configuration_error()
    (target_dir / "settings.yml").write_text("managed")
    (target_dir / "limiter.toml").unlink()
    assert "limiter.toml" in wrapper.configuration_error()


def test_existing_lock_does_not_hide_missing_config(tmp_path, monkeypatch, capsys):
    """A lock cannot certify files that have since disappeared."""
    wrapper = load_wrapper()
    lock = tmp_path / ".lock"
    lock.touch()
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper, "configuration_error", lambda: "missing limiter.toml")
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run"))

    assert wrapper.main(["install"]) == 1
    assert "missing limiter.toml" in capsys.readouterr().err


def test_start_rejects_stale_managed_config(tmp_path, monkeypatch, capsys):
    """Never launch containers behind a valid lock with missing config."""
    wrapper = load_wrapper()
    stack_dir = tmp_path / "stack-20_-_searxng_firecrawl"
    stack_dir.mkdir()
    (tmp_path / ".env").write_text("BASE_PATH=/tmp/runtime\n")
    (stack_dir / ".env").symlink_to("../.env")
    (stack_dir / "docker-compose.yml").write_text("services: {}\n")
    (stack_dir / ".lock").touch()
    monkeypatch.setattr(wrapper, "STACK_DIR", stack_dir)
    monkeypatch.setattr(wrapper, "LOCK_FILE", stack_dir / ".lock")
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    monkeypatch.setattr(wrapper, "configuration_error", lambda: "missing settings.yml")
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run"))

    assert wrapper.main(["start"]) == 1
    assert "missing settings.yml" in capsys.readouterr().err
