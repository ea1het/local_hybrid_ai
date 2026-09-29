# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Platform bootstrap and host prerequisite tools for all service stacks.

The package groups the scripts that create shared runtime directories, link
environment files, install the local CA and TLS material, and verify platform
readiness. Importing it does not prepare the host; run the documented CLI
entrypoints explicitly. Legacy directory and script names remain stable for
Compose, shell commands, and existing installations.
"""

import sys

sys.dont_write_bytecode = True
