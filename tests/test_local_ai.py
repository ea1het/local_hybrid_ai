# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Exercise the root dispatcher without starting or stopping containers.

Help and argument errors are safe subprocesses: they prove the executable
selects real stack wrappers and preserves their CLI behavior and exit codes.
"""

import subprocess
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


@pytest.mark.parametrize("number", ("00", "10", "20", "30", "40", "50", "60", "70"))
def test_forwards_stack_help(number):
    """Route to each stack binary and preserve its own verb help."""
    result = subprocess.run([ROOT / "local-ai", f"stack-{number}", "status", "--help"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "--deep" in result.stdout


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
