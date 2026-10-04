# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Report that Dockhand has no stack-managed reconfiguration operation.

Dockhand's persistent settings belong to its external volume and user-facing
application. This module deliberately leaves that volume and its container
unchanged rather than treating install as a configuration update.
"""

import argparse
import sys

sys.dont_write_bytecode = True


def main(apply: bool = False) -> int:
    print("Stack 50 has nothing to reconfigure. No containers or persistent data were changed.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Apply the displayed reconfiguration plan")
    raise SystemExit(main(parser.parse_args().apply))
