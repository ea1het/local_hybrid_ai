# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Group Stack 40 Gitea and runner behavior tests.

Preparation and deployment are covered as separate phases in this
package. Importing it does not run Gitea or register a runner."""

import sys

sys.dont_write_bytecode = True
