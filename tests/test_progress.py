# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Check that progress feedback never changes command results or pipe output."""

import io
import subprocess
import sys
import time
from types import SimpleNamespace

sys.dont_write_bytecode = True

from wrapper.lib import progress


def test_noninteractive_progress_preserves_subprocess_arguments(monkeypatch):
    """Avoid visual feedback when stderr is not a terminal."""
    calls = []

    def fake_run(*args, **kwargs):
        """Capture invocation and return a representative subprocess result."""
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=7, stdout="output", stderr="failure")

    monkeypatch.setattr(progress.subprocess, "run", fake_run)
    result = progress.run_with_progress("Preparing", ["false"], capture_output=True, text=True)
    assert result.returncode == 7
    assert calls == [((["false"],), {"capture_output": True, "text": True})]


def test_progress_works_with_real_command():
    """Preserve captured output and exit status without a terminal."""
    result = progress.run_with_progress("Checking", [sys.executable, "-B", "-c", "print('ok')"],
                                        capture_output=True, text=True, check=False)
    assert isinstance(result, subprocess.CompletedProcess)
    assert result.returncode == 0
    assert result.stdout.strip() == "ok"


def test_interactive_progress_is_indeterminate_and_cleared(monkeypatch):
    """Show elapsed activity only while a slow subprocess is running."""
    class Terminal(io.StringIO):
        """Collect writes while behaving like an interactive terminal."""

        def isatty(self):
            """Request the activity display."""
            return True

    terminal = Terminal()
    monkeypatch.setattr(progress.sys, "stderr", terminal)

    def slow_run(*args, **kwargs):
        """Keep the subprocess active long enough to show its progress bar."""
        time.sleep(0.55)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(progress.subprocess, "run", slow_run)
    assert progress.run_with_progress("Preparing", ["true"]).returncode == 0
    assert "Preparing" in terminal.getvalue()
    assert "%" not in terminal.getvalue()
