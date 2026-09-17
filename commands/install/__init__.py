# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Install command package.

The package is the command-domain boundary. The path-sensitive installer engine
is re-exported while its filesystem layout is migrated behind this package.
"""
from commands._install_legacy import *
