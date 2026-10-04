# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Open WebUI bootstrap, preparation, and readiness package.

Bootstrap creates missing operational values, preparation validates the
stack, and readiness checks the running service. Importing the package does
not invoke Docker or expose secrets; use the dedicated scripts for operations.
"""

import sys

sys.dont_write_bytecode = True
