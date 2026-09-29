# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Verify that every stack wrapper requires an argparse operation verb.

Only parsing and help are exercised in subprocesses. No stack installation
or Docker operation runs during these tests.
"""

import subprocess
import sys

sys.dont_write_bytecode = True

import pytest

from tests.helpers import ROOT


@pytest.mark.parametrize("number", ("00", "10", "20", "30", "40", "50", "60", "70"))
def test_install_is_required_subcommand(number):
    """Reject a missing or unknown verb and advertise install."""
    script = ROOT / "wrapper" / "bin" / f"stack-{number}.py"
    help_result = subprocess.run([sys.executable, "-B", str(script), "--help"],
                                 capture_output=True, text=True, check=False)
    assert help_result.returncode == 0
    assert "install" in help_result.stdout

    for arguments in ((), ("unknown",)):
        result = subprocess.run([sys.executable, "-B", str(script), *arguments],
                                capture_output=True, text=True, check=False)
        assert result.returncode == 2
        assert "usage:" in result.stderr

    install_help = subprocess.run([sys.executable, "-B", str(script), "install", "--help"],
                                  capture_output=True, text=True, check=False)
    assert install_help.returncode == 0
