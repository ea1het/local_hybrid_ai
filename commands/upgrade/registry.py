# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Package-owned registry implementation for Upgrade.

Upgrade deliberately carries its own copy while command packages are being
closed.  Shared implementation can be deduplicated after package boundaries
and public behaviour are stable.
"""
from commands.upgrade_registry import *
