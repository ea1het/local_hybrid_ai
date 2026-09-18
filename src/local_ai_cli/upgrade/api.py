# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Public upgrade command API backed by the package-owned implementation."""
import argparse
from ._entry_impl import *
def public_parser():
 p=argparse.ArgumentParser(prog="local-ai upgrade",description="Inspect versions, stage component upgrades, manage policy and apply a staged plan")
 p.add_argument("--offline",action="store_true",help="inspect installed state without querying upstream registries")
 p.add_argument("--json",action="store_true",help="emit one machine-readable JSON document; global option owned by local-ai")
 p.add_argument("--yes",action="store_true",help="grant non-interactive consent for mutations; global option owned by local-ai")
 p.add_argument("arguments",nargs="*",metavar="ARG",help="check | STACK [COMPONENT] <select VERSION|clear> | policy STACK [COMPONENT] [set POLICY|clear] | adopt")
 return p