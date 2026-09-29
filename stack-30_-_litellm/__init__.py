# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""LiteLLM gateway and dedicated PostgreSQL lifecycle package.

The package separates preparation of service configuration from database
role and database provisioning. Persistent PostgreSQL data is not recreated
by importing or preparing this package. Execute each operational script
explicitly after its documented prerequisites are satisfied.
"""

import sys

sys.dont_write_bytecode = True
