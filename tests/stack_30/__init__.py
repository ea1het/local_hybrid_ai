# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Group Stack 30 LiteLLM and PostgreSQL regression tests.

The package separates preparation checks from database provisioning
checks. Importing it does not read secrets or touch PostgreSQL."""

import sys

sys.dont_write_bytecode = True
