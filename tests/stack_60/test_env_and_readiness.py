# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Test Hermes environment parsing and container readiness behavior.

Fixtures cover variable expansion, quoting, missing settings, and mocked
container status. The tests avoid sourcing a real environment file or
contacting Docker. Importing the module only defines tests."""

import sys

sys.dont_write_bytecode = True

from types import SimpleNamespace

import pytest

from tests.helpers import load_module


env_module = load_module("stack-60_-_hermes", "stack_env.py")
ready = load_module("stack-60_-_hermes", "wait-ready.py")


def test_env_expands_prior_values_but_preserves_single_quoted_literals(tmp_path, monkeypatch):
    """Expand earlier values while preserving single-quoted literals."""
    monkeypatch.setenv("STACK_TEST_SEED", "outside")
    path = tmp_path / ".env"
    path.write_text(
        "ROOT=/runtime\nexport CHILD=${ROOT}/data # explanation\n"
        "LITERAL='$ROOT # kept'\nFROM_HOST=$STACK_TEST_SEED\n"
    )

    values = env_module.load_env(path)

    assert values["CHILD"] == "/runtime/data"
    assert values["LITERAL"] == "$ROOT # kept"
    assert values["FROM_HOST"] == "outside"


@pytest.mark.parametrize("line", ["VALUE=$(id)", "VALUE=`id`", "VALUE=one two", "VALUE='broken", "bad line"])
def test_env_rejects_unsupported_shell_syntax(tmp_path, line):
    """Reject shell expansion and malformed environment lines."""
    path = tmp_path / ".env"
    path.write_text(line + "\n")

    with pytest.raises(ValueError, match=r"\.env syntax|shell command expansion|\.env value|\.env quoting"):
        env_module.load_env(path)


def test_container_state_treats_failed_inspect_as_absent(monkeypatch):
    """Treat a failed Docker inspection as an absent container."""
    calls = []

    def fake_run(command, **kwargs):
        """Record Docker inspection and simulate its failure."""
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=1, stdout="")

    monkeypatch.setattr(ready.subprocess, "run", fake_run)
    assert ready.container_state("hermes") == "absent|"
    assert calls[0][0][:3] == ["docker", "inspect", "-f"]


def test_wait_ready_retries_unhealthy_container_then_succeeds(tmp_path, monkeypatch, capsys):
    """Retry starting containers until all required services are ready."""
    env_file = tmp_path / ".env"
    env_file.write_text("present\n")
    monkeypatch.setattr(ready, "ENV_FILE", env_file)
    monkeypatch.setattr(ready.shutil, "which", lambda command: "/usr/bin/docker")
    monkeypatch.setattr(ready, "load_env", lambda path: {
        "HERMES_CONTAINER": "hermes", "SANDBOX_CONTAINER": "sandbox",
        "SANDBOX_CLEANUP_CONTAINER": "cleanup",
    })
    states = iter(["running|starting", "running|healthy", "running|", "running|healthy", "running|healthy", "running|"])
    monkeypatch.setattr(ready, "container_state", lambda name: next(states))
    sleeps = []
    monkeypatch.setattr(ready.time, "sleep", sleeps.append)

    ready.main()

    assert sleeps == [2]
    assert "READY" in capsys.readouterr().out


def test_wait_ready_fails_immediately_on_dead_container(tmp_path, monkeypatch, capsys):
    """Fail without retrying when a required container is dead."""
    env_file = tmp_path / ".env"
    env_file.touch()
    monkeypatch.setattr(ready, "ENV_FILE", env_file)
    monkeypatch.setattr(ready.shutil, "which", lambda command: "/usr/bin/docker")
    monkeypatch.setattr(ready, "load_env", lambda path: {
        "HERMES_CONTAINER": "hermes", "SANDBOX_CONTAINER": "sandbox",
        "SANDBOX_CLEANUP_CONTAINER": "cleanup",
    })
    monkeypatch.setattr(ready, "container_state", lambda name: "dead|")
    monkeypatch.setattr(ready.time, "sleep", lambda seconds: pytest.fail("must not retry dead containers"))

    with pytest.raises(SystemExit, match="1"):
        ready.main()
    assert "failed before READY" in capsys.readouterr().err
