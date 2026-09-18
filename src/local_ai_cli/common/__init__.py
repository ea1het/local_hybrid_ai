#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Shared implementation primitives used by more than one command package.

Every command package may depend on ``local_ai_cli.common``; ``local_ai_cli.common``
must not depend on any command package. Code moves here only after it has
proven identical (or reconcilable) across the packages that duplicated it.
"""
