# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Report the platform's reconfiguration boundary without changing host state.

Stack 00 already reconciles its certificates, directories, links, and network
through the repeatable install audit. This command therefore does no work and
never starts or stops a container.
"""

import argparse
import sys

sys.dont_write_bytecode = True


def main(apply: bool = False) -> int:
    print("Stack 00 has nothing to reconfigure; ./local-ai stack-00 install already reconciles it.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Apply the displayed reconfiguration plan")
    raise SystemExit(main(parser.parse_args().apply))
