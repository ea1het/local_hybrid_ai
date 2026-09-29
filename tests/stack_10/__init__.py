# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Group Stack 10 reverse-proxy preparation tests.

The package keeps HAProxy and web frontend behavior checks separate from
other stacks. Importing it does not prepare or deploy the proxy."""

import sys

sys.dont_write_bytecode = True
