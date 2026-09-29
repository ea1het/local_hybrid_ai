# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""SearXNG and Firecrawl preparation and readiness package.

Its preparation module checks shared platform prerequisites, configures
persistent service data, and marks the stack prepared. Its readiness module
probes running containers and endpoints. Package import is side-effect free;
operational checks and changes occur only through the explicit scripts.
"""

import sys

sys.dont_write_bytecode = True
