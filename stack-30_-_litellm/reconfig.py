# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Reserve LiteLLM reconfiguration until its database ownership is defined.

Models, provider credentials, consumer keys, and MCP grants can be edited in
LiteLLM's database. Until their reconciliation contract is explicit, this
module must refuse changes rather than overwrite an operator's configuration.
"""

import argparse
import sys

sys.dont_write_bytecode = True


def main(apply: bool = False) -> int:
    print("Stack 30 reconfiguration is under development; no configuration was changed.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Apply the displayed reconfiguration plan")
    raise SystemExit(main(parser.parse_args().apply))
