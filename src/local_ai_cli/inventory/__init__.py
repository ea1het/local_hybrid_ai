# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Self-contained source inventory command package."""
from . import api
from .api import SCHEMA_VERSION,_error,json_payload,cli_text,main
__all__=["api","SCHEMA_VERSION","_error","json_payload","cli_text","main"]
