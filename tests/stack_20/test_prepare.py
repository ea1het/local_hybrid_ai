# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Test SearXNG and Firecrawl preparation with isolated runtime files.

Cases check platform prerequisites, configuration installation, preserved
secrets, and the preparation lock. Docker operations are replaced by
test doubles. Importing the module does not prepare services."""

import sys

sys.dont_write_bytecode = True

from types import SimpleNamespace

import pytest

from tests.helpers import load_module


def test_prepare_preserves_existing_secret_and_installs_config(tmp_path, monkeypatch):
    """Preserve the database secret while installing config and a lock."""
    module = load_module("stack-20_-_searxng_firecrawl", "01-prepare.py")
    stack_dir = tmp_path / module.STACK_NAME
    base = tmp_path / "runtime"
    service_paths = ("service_-_searxng/config", "service_-_searxng/data",
                     "service_-_firecrawl-redis/data", "service_-_firecrawl-rabbitmq/data",
                     "service_-_firecrawl-postgres/data", "service_-_firecrawl-postgres/secret")
    for path in service_paths:
        (base / path).mkdir(parents=True)
    for path in (stack_dir / "config/searxng/settings.yml",
                 stack_dir / "config/searxng/limiter.toml",
                 stack_dir / "config/postgres/020-firecrawl-app-role.sh",
                 tmp_path / "stack-00_-_platform/.lock"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    secret = base / "service_-_firecrawl-postgres/secret/postgres_admin_password"
    secret.write_text("preserved")
    (stack_dir / ".env").touch()
    (stack_dir / "docker-compose.yml").touch()
    monkeypatch.setattr(module, "STACK_DIR", stack_dir)
    monkeypatch.setattr(module, "ENV_FILE", stack_dir / ".env")
    monkeypatch.setattr(module, "COMPOSE_FILE", stack_dir / "docker-compose.yml")
    monkeypatch.setattr(module, "LOCK_FILE", stack_dir / ".lock")
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.os, "chown", lambda *args: None)
    monkeypatch.setattr(module.os, "umask", lambda mask: 0)
    monkeypatch.setattr(module.shutil, "which", lambda command: command)
    env = {key: "fixture" for key in module.REQUIRED}
    env.update(STACKS_ROOT=str(tmp_path), BASE_PATH=str(base), NETWORK_NAME="shared",
               SEARXNG_BASE_URL="https://search.example", FIRECRAWL_DB_USER="firecrawl",
               FIRECRAWL_DB_NAME="postgres")
    monkeypatch.setattr(module, "sourced_environment", lambda: env)
    commands = []

    def fake_run(command, **kwargs):
        """Record installation and Docker commands as successful."""
        commands.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module.subprocess, "check_output", lambda *args, **kwargs: b"bridge\n")

    module.main()

    assert secret.read_text() == "preserved"
    assert module.LOCK_FILE.read_text().startswith("stack=stack-20_-_searxng_firecrawl\n")
    assert [command[0] for command in commands].count("install") == 2
    assert any(command[:2] == ["docker", "compose"] and "config" in command for command in commands)


@pytest.mark.parametrize("key,value,message", [
    ("SEARXNG_BASE_URL", "http://search.example", "debe ser HTTPS"),
    ("FIRECRAWL_DB_USER", "postgres", "no puede ser postgres"),
    ("FIRECRAWL_DB_NAME", "firecrawl", "debe ser postgres"),
])
def test_prepare_rejects_invalid_database_and_url_settings(tmp_path, monkeypatch, capsys,
                                                           key, value, message):
    """Reject insecure URL or incompatible database settings."""
    module = load_module("stack-20_-_searxng_firecrawl", "01-prepare.py")
    monkeypatch.setattr(module, "STACK_DIR", tmp_path / module.STACK_NAME)
    monkeypatch.setattr(module, "LOCK_FILE", tmp_path / ".lock")
    monkeypatch.setattr(module, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(module, "COMPOSE_FILE", tmp_path / "compose.yml")
    module.ENV_FILE.touch()
    module.COMPOSE_FILE.touch()
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.shutil, "which", lambda command: command)
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    env = {name: "fixture" for name in module.REQUIRED}
    env.update(STACKS_ROOT=str(tmp_path), BASE_PATH=str(tmp_path / "base"),
               SEARXNG_BASE_URL="https://search.example", FIRECRAWL_DB_USER="firecrawl",
               FIRECRAWL_DB_NAME="postgres")
    env[key] = value
    monkeypatch.setattr(module, "sourced_environment", lambda: env)

    with pytest.raises(SystemExit, match="1"):
        module.main()
    assert message in capsys.readouterr().err
