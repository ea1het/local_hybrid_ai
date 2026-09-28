import sys

sys.dont_write_bytecode = True

import os
from types import SimpleNamespace

import pytest

from tests.helpers import load_module


def test_prepare_creates_volume_then_lock(tmp_path, monkeypatch):
    module = load_module("stack-50_-_dockhand", "01-prepare.py")
    stack_dir = tmp_path / module.STACK_NAME
    stack_dir.mkdir()
    (stack_dir / ".env").touch()
    (stack_dir / "docker-compose.yml").touch()
    (tmp_path / "stack-00_-_platform").mkdir()
    (tmp_path / "stack-00_-_platform/.lock").touch()
    env = {"STACKS_ROOT": str(tmp_path), "BASE_PATH": str(tmp_path / "runtime"),
           "NETWORK_NAME": "internal"}
    commands = []
    volume_inspects = iter([1, 0])

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[0] == "bash":
            return SimpleNamespace(stdout=b"\0".join(
                f"{key}={value}".encode() for key, value in env.items()) + b"\0")
        if command[:3] == ["docker", "volume", "inspect"] and len(command) == 4:
            return SimpleNamespace(returncode=next(volume_inspects))
        if command[-2:] == ["{{.Name}}", module.VOLUME]:
            return SimpleNamespace(returncode=0, stdout=module.VOLUME + "\n")
        return SimpleNamespace(returncode=0, stdout="bridge\n")

    monkeypatch.setattr(module, "STACK_DIR", stack_dir)
    monkeypatch.setattr(module, "ENV_FILE", stack_dir / ".env")
    monkeypatch.setattr(module, "COMPOSE_FILE", stack_dir / "docker-compose.yml")
    monkeypatch.setattr(module, "LOCK_FILE", stack_dir / ".lock")
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.os, "environ", os.environ.copy())
    monkeypatch.setattr(module.shutil, "which", lambda _: "/fake/docker")
    monkeypatch.setattr(module.subprocess, "run", fake_run)

    module.main()

    assert ["docker", "volume", "create", module.VOLUME] in commands
    assert any(command[-2:] == ["config", "--quiet"] for command in commands)
    assert "stack=stack-50_-_dockhand" in (stack_dir / ".lock").read_text()
    assert (stack_dir / ".lock").stat().st_mode & 0o777 == 0o644


def test_prepare_rejects_non_bridge_network_before_volume_creation(tmp_path, monkeypatch):
    module = load_module("stack-50_-_dockhand", "01-prepare.py")
    stack_dir = tmp_path / module.STACK_NAME
    stack_dir.mkdir()
    (stack_dir / ".env").touch()
    (stack_dir / "docker-compose.yml").touch()
    (tmp_path / "stack-00_-_platform").mkdir()
    (tmp_path / "stack-00_-_platform/.lock").touch()
    env = {"STACKS_ROOT": str(tmp_path), "BASE_PATH": str(tmp_path / "runtime"),
           "NETWORK_NAME": "internal"}
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[0] == "bash":
            return SimpleNamespace(stdout=b"\0".join(
                f"{key}={value}".encode() for key, value in env.items()) + b"\0")
        return SimpleNamespace(returncode=0, stdout="overlay\n")

    monkeypatch.setattr(module, "STACK_DIR", stack_dir)
    monkeypatch.setattr(module, "ENV_FILE", stack_dir / ".env")
    monkeypatch.setattr(module, "COMPOSE_FILE", stack_dir / "docker-compose.yml")
    monkeypatch.setattr(module, "LOCK_FILE", stack_dir / ".lock")
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.os, "environ", os.environ.copy())
    monkeypatch.setattr(module.shutil, "which", lambda _: "/fake/docker")
    monkeypatch.setattr(module.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="no bridge"):
        module.main()
    assert not any(command[:2] == ["docker", "volume"] for command in commands)
    assert not (stack_dir / ".lock").exists()
