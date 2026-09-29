# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Group the repository's Python regression tests in one package.

Test modules cover operational stack behavior, license headers, shebangs,
and bytecode hygiene. Importing this package disables local bytecode writes
before test helpers load stack code; it does not run pytest itself."""

import sys

sys.dont_write_bytecode = True
