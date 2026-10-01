# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Verify minimal LiteLLM key issuance without contacting Docker or oMLX."""

import io
import json
import os
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True

from tests.helpers import ROOT, load_module
from wrapper.stubs import bootstrap_env


def prepare_module(tmp_path, monkeypatch):
    """Point the installer at an isolated protected environment."""
    module = load_module("stack-30_-_litellm", "issue-consumer-keys.py")
    env = tmp_path / ".env"
    env.write_text("LITELLM_MASTER_KEY=sk-admin\nOMLX_API_KEY=upstream-secret\n"
                   "LITELLM_API_KEY=PUT_YOUR_LITELLM_API_KEY_HERE\n"
                   "LITELLM_MCP_API_KEY=PUT_YOUR_HERMES_MCP_API_KEY_HERE\n"
                   "OPENWEBUI_LITELLM_API_KEY=PUT_YOUR_OPENWEBUI_LITELLM_API_KEY_HERE\n")
    env.chmod(0o600)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "STACK_DIR", tmp_path)
    monkeypatch.setattr(module, "ENV_FILE", env)
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module, "root_owned", lambda _: True)
    monkeypatch.setattr(bootstrap_env, "root_owned", lambda _: True)
    monkeypatch.setattr(bootstrap_env, "private_owner", lambda descriptor: os.fchmod(descriptor, 0o600))
    return module, env


def test_issues_three_distinct_keys_without_inference(tmp_path, monkeypatch):
    """Mint scoped consumer keys, store each privately, and remove the proxy."""
    module, env = prepare_module(tmp_path, monkeypatch)
    calls = []

    def fake_run(command, **kwargs):
        """Model the temporary gateway and its key issuance responses."""
        calls.append(command)
        if command[:2] == ["docker", "inspect"]:
            return SimpleNamespace(returncode=1, stdout="")
        if command[:2] == ["docker", "exec"] and command[-1] in module.KEYS:
            return SimpleNamespace(returncode=0, stdout=json.dumps({"key": f"sk-{command[-1]}"}))
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    assert module.issue_keys() == list(module.KEYS.values())
    values = bootstrap_env.assignments(env.read_text())
    for role, name in module.KEYS.items():
        assert values[name] == f"sk-{role}"
    assert list(tmp_path.glob(".env-backup-*"))
    assert any(command[-1] == "litellm" for command in calls)
    assert calls[-1] == ["docker", "rm", "-f", module.CONTAINER]
    assert not any("chat/completions" in " ".join(command) for command in calls)
    calls.clear()
    assert module.issue_keys() == []
    assert calls == []


def test_refuses_missing_upstream_key_before_docker(tmp_path, monkeypatch):
    """A template oMLX key must not trigger a temporary container."""
    module, env = prepare_module(tmp_path, monkeypatch)
    env.write_text(env.read_text().replace("OMLX_API_KEY=upstream-secret",
                                           "OMLX_API_KEY=PUT_YOUR_OMLX_API_KEY_HERE"))
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("Docker must not be called")))
    try:
        module.issue_keys()
    except bootstrap_env.BootstrapError as error:
        assert "OMLX_API_KEY" in str(error)
    else:
        raise AssertionError("missing oMLX key was accepted")


def test_models_are_not_declared_in_proxy_config():
    """Leave database-managed models editable in the LiteLLM Admin UI."""
    config = (ROOT / "stack-30_-_litellm/config/litellm/config.yaml").read_text()
    assert "model_list:" not in config
    assert "credential_list:" not in config


def test_key_payloads_limit_models_and_start_without_mcp_grants(monkeypatch, capsys):
    """Give Hermes and WebUI fixed models but no implicit MCP permissions."""
    import urllib.request

    module = load_module("stack-30_-_litellm", "issue-consumer-keys.py")
    bodies = []

    def fake_open(request, timeout):
        """Return a virtual key or the complete fixed model list."""
        if request.data:
            bodies.append(json.loads(request.data))
            result = {"key": "sk-issued"}
        else:
            result = {"data": [{"id": model} for model in module.MODELS]}
        return io.BytesIO(json.dumps(result).encode())

    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-admin")
    monkeypatch.setattr(urllib.request, "urlopen", fake_open)
    for role in module.KEYS:
        monkeypatch.setattr(sys, "argv", ["script", role])
        exec(module.KEY_SCRIPT, {})
    assert len(bodies) == 3
    for body in bodies:
        assert body["object_permission"]["mcp_servers"] == ["no-mcp-servers"]
    assert bodies[0]["models"] == list(module.MODELS)
    assert bodies[1]["allowed_routes"] == ["mcp_routes"]
    assert "models" not in bodies[1]
    assert bodies[2]["models"] == list(module.MODELS)
    assert capsys.readouterr().out.count("sk-issued") == 3
