# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Test the Stack 60 wrapper without touching Hermes runtime state.

The Python entrypoint is loaded without running its CLI. Temporary
locks and mocked subprocess calls verify scoped bootstrap ordering, package
invocation, lock safety, failure propagation, and optional-operation exclusion.
"""

import importlib.machinery
import importlib.util
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True

import pytest

from tests.helpers import ROOT


def load_wrapper():
    """Load the Stack 60 wrapper without invoking its main function."""
    path = ROOT / "wrapper/bin/stack-60.py"
    loader = importlib.machinery.SourceFileLoader("stack_60_wrapper_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_existing_lock_skips_preparation_and_optional_actions(tmp_path, monkeypatch, capsys):
    """Preserve a locked runtime and show only manual deployment guidance."""
    wrapper = load_wrapper()
    lock = tmp_path / ".lock"
    lock.write_text("prepared")
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run"))

    assert wrapper.main(["install"]) == 0
    output = capsys.readouterr().out
    assert "Removing .lock manually" in output
    assert "./local-ai stack-60 start" in output
    assert "cleanup are separate operations" in output


def test_missing_lock_bootstraps_then_prepares(tmp_path, monkeypatch, capsys):
    """Create service directories before Hermes preparation with closed stdin."""
    wrapper = load_wrapper()
    lock = tmp_path / ".lock"
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    platform = tmp_path / "stack-00_-_platform"
    platform.mkdir()
    (platform / ".lock").write_text("prepared")
    monkeypatch.setattr(wrapper, "ROOT", tmp_path)
    calls = []

    def fake_run(command, **kwargs):
        """Capture both phases and simulate a successful preparation audit."""
        calls.append((command, kwargs))
        if command[-1] == wrapper.PREPARE_MODULE:
            lock.write_text("prepared")
        return SimpleNamespace(returncode=0, stdout="audit passed\n", stderr="")

    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)
    assert wrapper.main(["install"]) == 0
    assert calls[0][0] == [sys.executable, "-B", str(platform / "00-bootstrap.py"), "--stack", "60"]
    command, options = calls[1]
    assert command == [sys.executable, "-B", "-m", wrapper.PREPARE_MODULE]
    assert len(calls) == 2
    assert options["stdin"] == wrapper.subprocess.DEVNULL
    assert options["cwd"] == tmp_path
    assert str(tmp_path) in options["env"]["PYTHONPATH"].split(wrapper.os.pathsep)
    assert "audit passed\n" in capsys.readouterr().out


def test_prepare_failure_does_not_claim_hermes_ready(tmp_path, monkeypatch, capsys):
    """Preserve a failing exit code without printing startup instructions."""
    wrapper = load_wrapper()
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", tmp_path / ".lock")
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    platform = tmp_path / "stack-00_-_platform"
    platform.mkdir()
    (platform / ".lock").write_text("prepared")
    monkeypatch.setattr(wrapper, "ROOT", tmp_path)
    calls = []

    def fake_run(command, **kwargs):
        """Succeed during bootstrap and fail during Hermes preparation."""
        calls.append(command)
        if command[-1] == wrapper.PREPARE_MODULE:
            return SimpleNamespace(returncode=8, stdout="", stderr="audit failed\n")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)

    assert wrapper.main(["install"]) == 8
    captured = capsys.readouterr()
    assert "audit failed" in captured.err
    assert "docker compose" not in captured.out
    assert len(calls) == 2


def test_bootstrap_failure_does_not_run_prepare(tmp_path, monkeypatch, capsys):
    """Stop after directory bootstrap fails without invoking Hermes preparation."""
    wrapper = load_wrapper()
    platform = tmp_path / "stack-00_-_platform"
    platform.mkdir()
    (platform / ".lock").write_text("prepared")
    monkeypatch.setattr(wrapper, "ROOT", tmp_path)
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", tmp_path / ".lock")
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    calls = []

    def fake_run(command, **kwargs):
        """Record the sole bootstrap call and its failure."""
        calls.append(command)
        return SimpleNamespace(returncode=7, stdout="", stderr="bootstrap failed\n")

    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)
    assert wrapper.main(["install"]) == 7
    assert len(calls) == 1
    assert calls[0][-2:] == ["--stack", "60"]
    assert "directory preparation failed" in capsys.readouterr().err


def test_missing_platform_lock_stops_before_bootstrap(tmp_path, monkeypatch):
    """Avoid creating Hermes directories without a prepared platform."""
    wrapper = load_wrapper()
    monkeypatch.setattr(wrapper, "ROOT", tmp_path)
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", tmp_path / ".lock")
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run"))

    assert wrapper.main(["install"]) == 1


def test_symlink_lock_is_rejected_without_execution(tmp_path, monkeypatch):
    """Refuse a redirected preparation lock before calling the stack module."""
    wrapper = load_wrapper()
    target = tmp_path / "target"
    target.write_text("prepared")
    lock = tmp_path / ".lock"
    lock.symlink_to(target)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run"))

    assert wrapper.main(["install"]) == 1


def test_stop_includes_optional_memory_sync_profile(tmp_path, monkeypatch, capsys):
    """Stop the opt-in sync sidecar without enabling it for normal start."""
    wrapper = load_wrapper()
    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()
    monkeypatch.setattr(wrapper, "STACK_DIR", stack_dir)
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    (stack_dir / ".env").symlink_to("../.env")
    (tmp_path / ".env").write_text("TEST=1\n")
    (stack_dir / "docker-compose.yml").write_text("services: {}\n")
    calls = []

    def fake_run(command, **kwargs):
        """Capture the Compose command without contacting Docker."""
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)
    assert wrapper.run_compose("down") == 0
    assert calls[0][0] == ["docker", "compose", "--env-file", ".env", "-f",
                           "docker-compose.yml", "--profile", "git-memory", "down"]
    assert calls[0][1]["cwd"] == stack_dir
    assert "stopped and removed" in capsys.readouterr().out


def test_start_removes_stale_gateway_overrides_before_compose(tmp_path, monkeypatch):
    """Recycle Hermes' old runtime key without invoking interactive setup."""
    wrapper = load_wrapper()
    stack_dir = tmp_path / "stack-60_-_hermes"
    stack_dir.mkdir()
    (stack_dir / ".env").symlink_to("../.env")
    (tmp_path / ".env").write_text("protected\n")
    (stack_dir / "docker-compose.yml").touch()
    lock = stack_dir / ".lock"
    lock.touch()
    runtime = tmp_path / "runtime/service_-_hermes"
    (runtime / "data").mkdir(parents=True)
    (runtime / "config").mkdir()
    runtime_env = runtime / "data/.env"
    runtime_env.write_text("LITELLM_API_KEY=old\nOTHER=keep\n")
    runtime_env.chmod(0o600)
    config = runtime / "config/config.yaml"
    config.write_text("model:\n  base_url: http://old/v1\n  api_key: old\n"
                      "mcp_servers:\n  litellm_gateway:\n    url: http://old/mcp\n"
                      "      Authorization: \"Bearer old\"\n")
    config.chmod(0o640)
    monkeypatch.setattr(wrapper, "ROOT", tmp_path)
    monkeypatch.setattr(wrapper, "STACK_DIR", stack_dir)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    monkeypatch.setattr(wrapper, "protected_text", lambda _: (
        f"BASE_PATH={tmp_path / 'runtime'}\nHERMES_SERVICE=service_-_hermes\nHERMES_CONTAINER=hermes\n"))
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[:2] == ["docker", "ps"]:
            return SimpleNamespace(returncode=0, stdout="hermes running\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)
    monkeypatch.setattr(wrapper, "run_with_progress", lambda label, command, **kwargs: fake_run(command, **kwargs))
    assert wrapper.run_compose("up") == 0
    assert any(command[-2:] == ["stop", "hermes"] for command in calls)
    assert calls[-1][-4:] == ["up", "-d", "--build", "--force-recreate"]
    assert runtime_env.read_text() == "OTHER=keep\n"
    assert "${LITELLM_API_KEY}" in config.read_text()
    assert all("setup" not in command for command in calls)
