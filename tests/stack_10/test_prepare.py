# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Test HAProxy and web frontend preparation in temporary trees.

Cases verify environment validation, TLS prerequisites, rendered files,
and the preparation lock without touching the live reverse proxy.
Importing this test module only defines fixtures and test functions."""

import sys

sys.dont_write_bytecode = True

from types import SimpleNamespace

import pytest

from tests.helpers import load_module


def test_sourced_environment_rejects_redacted_values(tmp_path, monkeypatch, capsys):
    """Reject redacted environment values before invoking Bash."""
    module = load_module("stack-10_-_haproxy_web", "01-prepare.py")
    env_file = tmp_path / ".env"
    env_file.write_text("WEB_TARGET=<REDACTED>\n")
    monkeypatch.setattr(module, "ENV_FILE", env_file)
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: pytest.fail("bash must not run"))

    with pytest.raises(SystemExit, match="1"):
        module.sourced_environment()
    assert "saneados/incompletos" in capsys.readouterr().err


def test_prepare_validates_tls_and_writes_lock_in_temporary_tree(tmp_path, monkeypatch):
    """Validate TLS setup and write the preparation lock after success."""
    module = load_module("stack-10_-_haproxy_web", "01-prepare.py")
    stack_dir = tmp_path / module.STACK_NAME
    base = tmp_path / "runtime"
    for path in (stack_dir / "config/haproxy", stack_dir / "config/web",
                 base / "service_-_haproxy/config", base / "service_-_web",
                 tmp_path / "stack-00_-_platform"):
        path.mkdir(parents=True)
    (stack_dir / "config/haproxy/haproxy.cfg").write_text("global\n")
    (stack_dir / "config/web/index.html").write_text("hello")
    for name in ("tls.crt", "tls.key"):
        (base / "service_-_haproxy/config" / name).write_text("test fixture")
    (tmp_path / "stack-00_-_platform/.lock").touch()
    (stack_dir / ".env").touch()
    (stack_dir / "docker-compose.yml").touch()
    monkeypatch.setattr(module, "STACK_DIR", stack_dir)
    monkeypatch.setattr(module, "ENV_FILE", stack_dir / ".env")
    monkeypatch.setattr(module, "COMPOSE_FILE", stack_dir / "docker-compose.yml")
    monkeypatch.setattr(module, "LOCK_FILE", stack_dir / ".lock")
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.os, "umask", lambda mask: 0)
    monkeypatch.setattr(module.shutil, "which", lambda command: f"/fake/{command}")
    env = {key: "example" for key in module.REQUIRED}
    env.update(STACKS_ROOT=str(tmp_path), BASE_PATH=str(base), NETWORK_NAME="shared",
               PLATFORM_PKI_GID="1999")
    monkeypatch.setattr(module, "sourced_environment", lambda: env)
    commands = []
    real_run = module.subprocess.run

    def fake_subprocess(command, **kwargs):
        """Record subprocess calls and simulate successful commands."""
        commands.append(command)
        return SimpleNamespace(returncode=0)

    def fake_output(command, **kwargs):
        """Return a bridge driver or matching TLS public key for probes."""
        return b"bridge\n" if command[:2] == ["docker", "network"] else b"matching-public-key"

    monkeypatch.setattr(module.subprocess, "run", fake_subprocess)
    monkeypatch.setattr(module.subprocess, "check_output", fake_output)
    def fake_run(*command, **kwargs):
        """Run only the web copy so the test checks its actual destination."""
        commands.append(command)
        if command[0] == "cp":
            real_run(command, check=True)

    monkeypatch.setattr(module, "run", fake_run)

    module.main()

    assert (base / "service_-_web/index.html").read_text() == "hello"
    assert not (base / "service_-_web/web").exists()
    assert "stack=stack-10_-_haproxy_web" in module.LOCK_FILE.read_text()
    assert any(command[:3] == ["docker", "run", "--rm"] and "--group-add" in command
               for command in commands)
    assert any(command[:2] == ("docker", "compose") for command in commands)


def test_prepare_rejects_invalid_pki_group_before_network_access(tmp_path, monkeypatch, capsys):
    """Reject an invalid PKI group before any network access."""
    module = load_module("stack-10_-_haproxy_web", "01-prepare.py")
    monkeypatch.setattr(module, "LOCK_FILE", tmp_path / ".lock")
    monkeypatch.setattr(module, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(module, "COMPOSE_FILE", tmp_path / "compose.yml")
    module.ENV_FILE.touch()
    module.COMPOSE_FILE.touch()
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.shutil, "which", lambda command: command)
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    env = {key: "value" for key in module.REQUIRED}
    env["PLATFORM_PKI_GID"] = "0"
    monkeypatch.setattr(module, "sourced_environment", lambda: env)

    with pytest.raises(SystemExit, match="1"):
        module.main()
    assert "entero positivo" in capsys.readouterr().err
