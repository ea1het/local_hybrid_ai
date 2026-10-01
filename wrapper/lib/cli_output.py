# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Frame stack CLI output with a blank line before and after execution.

The stack wrappers share this presentation boundary so install, lifecycle,
status, help, and error paths leave consistent space around their output.
The wrapper does not capture subprocess streams or alter exit codes, making
it suitable for a future terminal footer without changing stack operations.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

from functools import wraps
from typing import Callable, TypeVar

Main = TypeVar("Main", bound=Callable[..., int])


def spaced_output(main: Main) -> Main:
    """Add terminal breathing room even when parsing or execution fails."""
    @wraps(main)
    def framed(*args, **kwargs):
        print(flush=True)
        try:
            return main(*args, **kwargs)
        finally:
            print(flush=True)

    return framed
