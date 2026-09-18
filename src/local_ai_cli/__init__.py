#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Implementation package behind the sole public ./local-ai entry point.

Public command domains are packages. These aliases keep the existing dispatcher
stable while command-specific implementation is progressively internalized.
"""

__version__ = "0.1.0"

from .install import api as install_entry
from .lifecycle import api as runtime_lifecycle
from .upgrade import api as upgrade_entry
from .upgrade import adopt as upgrade_adopt
