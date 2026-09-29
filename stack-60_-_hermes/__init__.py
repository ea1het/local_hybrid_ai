# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Hermes agent preparation, maintenance, and cleanup package.

The stack contains environment parsing, readiness checks, optional Buzz and
Git-memory setup, capability reconciliation, and explicitly controlled
cleanup. Runtime and sandbox scripts are kept beside their deployment
configuration. Importing this package never starts containers, provisions
secrets, or removes data; those actions require the relevant CLI entrypoint.
"""

import sys

sys.dont_write_bytecode = True
