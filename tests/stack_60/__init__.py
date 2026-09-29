# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Group Stack 60 Hermes safety and lifecycle tests.

The package covers configuration, readiness, optional integrations,
sandbox state, and cleanup in isolated fixtures. Importing it does not
prepare or delete Hermes runtime data."""

import sys

sys.dont_write_bytecode = True
