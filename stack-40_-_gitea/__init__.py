# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Gitea server and runner preparation and deployment package.

Preparation renders configuration and checks prerequisites without starting
the service. Deployment is a separate operation that starts Gitea and checks
runner registration. Importing the package does not execute either phase or
access operational credentials.
"""

import sys

sys.dont_write_bytecode = True
