# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Install command domain.

Only the public install API is exposed here. Shared manifest/runtime installer
primitives live in ``commands.installer`` and are intentionally not re-exported
through the command package.
"""
from . import api
from .api import SCHEMA_VERSION,InstallArgumentParser,parser,build_payload,json_payload,cli_text,main
__all__=["api","SCHEMA_VERSION","InstallArgumentParser","parser","build_payload","json_payload","cli_text","main"]
