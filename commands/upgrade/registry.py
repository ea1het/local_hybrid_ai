# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Upgrade-package registry implementation.

Package-local copy used while command domains are being closed. The legacy
module remains in place for consumers that have not migrated yet.
"""
from commands.upgrade_registry import *
