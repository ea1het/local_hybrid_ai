# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Exercise the root dispatcher without starting or stopping containers.

Help and argument errors are safe subprocesses: they prove the executable
selects real stack wrappers and preserves their CLI behavior and exit codes.
"""

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
    (["stack-60", ""], "start"),
    (["stack-60", "status", ""], "--deep"),
    (["env", ""], "bootstrap"),
    (["completion", ""], "zsh"),
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
    ("00", ("install", "status")),
    *((number, ("install", "start", "stop", "status"))
      for number in ("10", "20", "30", "40", "50", "60", "70")),
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
