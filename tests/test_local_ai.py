# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Exercise the root dispatcher without starting or stopping containers.

Help and argument errors are safe subprocesses: they prove the executable
selects real stack wrappers and preserves their CLI behavior and exit codes.
"""

import importlib.machinery
import importlib.util
import os
import subprocess
import shutil
import sys

sys.dont_write_bytecode = True

import pytest

from tests.helpers import ROOT


def test_help_lists_available_wrappers():
    """Expose every current wrapper without its Python suffix."""
    result = subprocess.run([ROOT / "local-ai", "--help"], capture_output=True,
                            text=True, check=False)
    assert result.returncode == 0
    for number in ("00", "10", "20", "30", "40", "50", "60", "70"):
        assert f"stack-{number}" in result.stdout
        assert f"stack-{number}.py" not in result.stdout
    assert "env" in result.stdout


def test_environment_bootstrap_help():
    """Expose the explicit secret bootstrap verb without running it."""
    result = subprocess.run([ROOT / "local-ai", "env", "--help"], capture_output=True,
                            text=True, check=False)
    assert result.returncode == 0
    assert "bootstrap" in result.stdout
    assert "issue-litellm-keys" not in result.stdout


@pytest.mark.parametrize("number", ("00", "10", "20", "30", "40", "50", "60", "70"))
def test_forwards_stack_help(number):
    """Route to each stack binary and preserve its own verb help."""
    result = subprocess.run([ROOT / "local-ai", f"stack-{number}", "status", "--help"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "--deep" in result.stdout
    assert f"usage: ./local-ai stack-{number} status" in result.stdout
    assert f"stack-{number}.py" not in result.stdout


def test_preserves_wrapper_error_and_rejects_missing_command():
    """Do not swallow argparse failures or invent a missing stack binary."""
    rejected = subprocess.run([ROOT / "local-ai", "stack-10", "invalid"],
                              capture_output=True, text=True, check=False)
    assert rejected.returncode == 2
    assert "invalid choice" in rejected.stderr

    unknown = subprocess.run([ROOT / "local-ai", "stack-01", "install"],
                             capture_output=True, text=True, check=False)
    assert unknown.returncode == 2
    assert "Unknown command: stack-01" in unknown.stderr


@pytest.mark.parametrize("words,expected", [
    ([], "stack-60"),
    (["stack-00", ""], "status"),
    (["stack-00", ""], "reconfig"),
    (["stack-60", ""], "start"),
    (["stack-60", ""], "reconfig"),
    (["stack-60", "status", ""], "--deep"),
    (["env", ""], "bootstrap"),
    (["completion", ""], "zsh"),
    (["completion", "zsh", ""], "install"),
    (["completion", "bash", ""], "status"),
])
def test_completion_candidates(words, expected):
    """Offer top-level commands, verbs, and verb-specific options."""
    result = subprocess.run([ROOT / "local-ai", "__complete", *words], capture_output=True,
                            text=True, check=False)
    assert result.returncode == 0
    assert expected in result.stdout.splitlines()


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_completion_scripts_are_valid_shell(shell):
    """Produce a sourceable completion definition for supported shells."""
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} is not installed")
    result = subprocess.run([ROOT / "local-ai", "completion", shell], capture_output=True,
                            text=True, check=False)
    assert result.returncode == 0
    checked = subprocess.run([shell, "-n"], input=result.stdout, capture_output=True,
                             text=True, check=False)
    assert checked.returncode == 0, checked.stderr


@pytest.mark.parametrize("number,verbs", [
    ("00", ("install", "status", "reconfig")),
    *((number, ("install", "start", "stop", "status", "reconfig"))
      for number in ("10", "20", "30", "50", "60", "70")),
    ("40", ("install", "start", "stop", "status")),
])
def test_completion_matches_stack_parser_options(number, verbs):
    """Reject completion metadata that invents a verb or omits its options."""
    command = f"stack-{number}"
    for verb in verbs:
        help_result = subprocess.run([ROOT / "local-ai", command, verb, "--help"],
                                     capture_output=True, text=True, check=False)
        candidates = subprocess.run([ROOT / "local-ai", "__complete", command, verb, ""],
                                    capture_output=True, text=True, check=False)
        assert help_result.returncode == candidates.returncode == 0
        for option in candidates.stdout.splitlines():
            assert option in help_result.stdout
        if verb == "status":
            assert "--deep" in candidates.stdout.splitlines()


def test_reconfig_help_has_no_lifecycle_options():
    """Expose reconfiguration without implying automatic container changes."""
    result = subprocess.run([ROOT / "local-ai", "stack-60", "reconfig", "--help"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "--restart" not in result.stdout


def load_dispatcher():
    """Import the suffix-less executable so pure helpers can be tested in process."""
    loader = importlib.machinery.SourceFileLoader("local_ai_dispatcher", str(ROOT / "local-ai"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def isolated_env(tmp_path, **extra):
    """Keep install/status away from the real home, startup files, and system dirs."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {**os.environ, "HOME": str(home), "ZDOTDIR": str(home),
           "LOCAL_AI_COMPLETION_DIR": str(tmp_path / "completions"), **extra}
    env.pop("XDG_DATA_HOME", None)
    env.pop("BASH_COMPLETION_USER_DIR", None)
    return env


def test_completion_rejects_unknown_shell_or_action():
    """Fail with usage instead of guessing a shell or an action."""
    for arguments in (["fish"], ["zsh", "uninstall"], ["zsh", "install", "extra"]):
        result = subprocess.run([ROOT / "local-ai", "completion", *arguments],
                                capture_output=True, text=True, check=False)
        assert result.returncode == 2
        assert "completion {bash,zsh} [install|status]" in result.stderr
    candidates = subprocess.run([ROOT / "local-ai", "__complete", "completion", "fish", ""],
                                capture_output=True, text=True, check=False)
    assert candidates.stdout.strip() == ""


@pytest.mark.parametrize("euid,shell,expected", [
    (0, "zsh", "/usr/local/share/zsh/site-functions/_local-ai"),
    (0, "bash", "/usr/local/share/bash-completion/completions/local-ai"),
    (1000, "zsh", "/home/u/.local/share/zsh/site-functions/_local-ai"),
    (1000, "bash", "/home/u/.local/share/bash-completion/completions/local-ai"),
])
def test_completion_target_follows_privileges(monkeypatch, euid, shell, expected):
    """Install system-wide as root and into XDG user directories otherwise."""
    dispatcher = load_dispatcher()
    monkeypatch.setattr(dispatcher.os, "geteuid", lambda: euid)
    for name in ("LOCAL_AI_COMPLETION_DIR", "XDG_DATA_HOME", "BASH_COMPLETION_USER_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", "/home/u")
    assert str(dispatcher.completion_target(shell)) == expected


@pytest.mark.parametrize("shell,filename", [("bash", "local-ai"), ("zsh", "_local-ai")])
def test_completion_install_is_idempotent_and_status_detects_edits(tmp_path, shell, filename):
    """Write a valid file once, leave it unchanged after, and flag local edits."""
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} is not installed")
    env = isolated_env(tmp_path)
    target = tmp_path / "completions" / filename
    first = subprocess.run([ROOT / "local-ai", "completion", shell, "install"],
                           capture_output=True, text=True, env=env, check=False)
    assert first.returncode in (0, 1), first.stderr
    assert f"Installed: {target}" in first.stdout
    assert "installed and current" in first.stdout
    checked = subprocess.run([shell, "-n", target], capture_output=True, text=True, check=False)
    assert checked.returncode == 0, checked.stderr

    second = subprocess.run([ROOT / "local-ai", "completion", shell, "install"],
                            capture_output=True, text=True, env=env, check=False)
    assert f"Unchanged: {target}" in second.stdout

    target.write_text(target.read_text() + "# local edit\n")
    status = subprocess.run([ROOT / "local-ai", "completion", shell, "status"],
                            capture_output=True, text=True, env=env, check=False)
    assert status.returncode == 1
    assert "outdated or edited" in status.stdout


def test_zsh_status_reports_missing_setup_then_activation(tmp_path):
    """Name the missing zsh setup, then confirm a login shell activates the file."""
    if shutil.which("zsh") is None:
        pytest.skip("zsh is not installed")
    env = isolated_env(tmp_path)
    directory = tmp_path / "completions"
    installed = subprocess.run([ROOT / "local-ai", "completion", "zsh", "install"],
                               capture_output=True, text=True, env=env, check=False)
    assert installed.returncode == 1
    assert "directory is not in $fpath" in installed.stdout

    (tmp_path / "home" / ".zshrc").write_text(
        f"fpath=({directory} $fpath)\nautoload -Uz compinit && compinit -u\n")
    status = subprocess.run([ROOT / "local-ai", "completion", "zsh", "status"],
                            capture_output=True, text=True, env=env, check=False)
    assert status.returncode == 0, status.stdout
    assert "local-ai completes from the installed file" in status.stdout
