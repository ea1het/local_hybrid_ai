#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Compatibility installer implementation retained while remaining packages are closed."""
from commands.install._engine_impl import *

if __name__ == "__main__":
    raise SystemExit(main())
