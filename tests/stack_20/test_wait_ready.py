# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import sys

sys.dont_write_bytecode = True

from types import SimpleNamespace

import pytest

from tests.helpers import load_module


def test_probes_interpret_docker_results(monkeypatch):
    module = load_module("stack-20_-_searxng_firecrawl", "wait-ready.py")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=b"true\n")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    assert module.running("searxng")
    assert module.tcp_ready("searxng", "8080")
    assert calls[0] == ["docker", "inspect", "-f", "{{.State.Running}}", "searxng"]
    assert calls[1][-2:] == ["searxng", "8080"]
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=b""))
    assert not module.running("searxng")
    assert not module.tcp_ready("searxng", "8080")


def test_wait_ready_retries_until_both_endpoints_pass(tmp_path, monkeypatch, capsys):
    module = load_module("stack-20_-_searxng_firecrawl", "wait-ready.py")
    monkeypatch.setattr(module, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(module, "LOCK_FILE", tmp_path / ".lock")
    module.ENV_FILE.touch()
    module.LOCK_FILE.touch()
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.shutil, "which", lambda command: command)
    monkeypatch.setenv("STACK2_READY_TIMEOUT_SECONDS", "3")
    probes = []
    monkeypatch.setattr(module, "running", lambda name: True)

    def tcp_ready(host, port):
        probes.append((host, port))
        return len(probes) > 2

    monkeypatch.setattr(module, "tcp_ready", tcp_ready)
    monkeypatch.setattr(module.time, "time", lambda: 0)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)

    module.main()

    assert probes == [("searxng", "8080"), ("searxng", "8080"),
                      ("searxng", "8080"), ("firecrawl-api", "3002")]
    assert "firecrawl-api:3002: READY" in capsys.readouterr().out


def test_wait_ready_times_out_without_sleeping(tmp_path, monkeypatch, capsys):
    module = load_module("stack-20_-_searxng_firecrawl", "wait-ready.py")
    monkeypatch.setattr(module, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(module, "LOCK_FILE", tmp_path / ".lock")
    module.ENV_FILE.touch()
    module.LOCK_FILE.touch()
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.shutil, "which", lambda command: command)
    monkeypatch.setenv("STACK2_READY_TIMEOUT_SECONDS", "0")
    monkeypatch.setattr(module, "running", lambda name: False)
    monkeypatch.setattr(module.time, "time", lambda: 0)

    with pytest.raises(SystemExit, match="1"):
        module.main()
    assert "within 0s" in capsys.readouterr().err
