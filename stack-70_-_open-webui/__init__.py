# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Open WebUI bootstrap, preparation, readiness, and model-policy package.

Bootstrap creates missing operational values, preparation validates the
stack, and readiness and policy scripts inspect or reconcile the running
service. The policy scripts execute their embedded code inside the Open
WebUI container. Importing the package does not invoke Docker or expose
secrets; use the dedicated scripts for operational actions.
"""

import sys

sys.dont_write_bytecode = True
