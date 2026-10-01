# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Show truthful activity feedback while a captured CLI subprocess runs.

Stack wrappers capture child output to preserve error reporting and phase
boundaries. On an interactive terminal this helper displays an indeterminate
bar after a short delay, so long image pulls or container startup do not look
stuck. It never claims a percentage or hides the child's eventual output.
Noninteractive execution behaves exactly like subprocess.run.
"""

from __future__ import annotations

import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.dont_write_bytecode = True


def run_with_progress(label: str, *args, **kwargs) -> subprocess.CompletedProcess:
    """Run a command while animating an indeterminate bar on interactive stderr."""
    if not sys.stderr.isatty():
        return subprocess.run(*args, **kwargs)

    started = time.monotonic()
    width = 12
    line_length = 0
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(subprocess.run, *args, **kwargs)
        try:
            while not future.done():
                elapsed = time.monotonic() - started
                if elapsed >= 0.4:
                    position = int(elapsed * 5) % width
                    bar = "=" * position + ">" + " " * (width - position - 1)
                    line = f"[{bar}] {label} ({elapsed:.0f}s)"
                    line_length = max(line_length, len(line))
                    print("\r" + line.ljust(line_length), end="", file=sys.stderr, flush=True)
                time.sleep(0.1)
            return future.result()
        finally:
            if line_length:
                print("\r" + " " * line_length + "\r", end="", file=sys.stderr, flush=True)
