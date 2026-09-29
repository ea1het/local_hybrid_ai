# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""HAProxy and web frontend preparation package.

The package contains the preparation script for the reverse proxy and web
service. Preparation validates the platform network and TLS files, renders
runtime configuration, and records the prepared state. Importing the package
does not contact Docker or change host files; invoke the CLI script to do so.
"""

import sys

sys.dont_write_bytecode = True
