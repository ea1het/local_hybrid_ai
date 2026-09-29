# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Dockhand persistent-volume preparation package.

The stack has one operational preparation module. It verifies platform
prerequisites and the Docker volume used for Dockhand's data before writing
its preparation lock. Importing the package only establishes a Python
namespace and does not create volumes or modify the host.
"""

import sys

sys.dont_write_bytecode = True
