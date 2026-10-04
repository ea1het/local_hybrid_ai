"""Reserve LiteLLM reconfiguration until its database ownership is defined.

Models, provider credentials, consumer keys, and MCP grants can be edited in
LiteLLM's database. Until their reconciliation contract is explicit, this
module must refuse changes rather than overwrite an operator's configuration.
"""

import argparse
import sys

sys.dont_write_bytecode = True


def main() -> int:
    print("Stack 30 reconfiguration is under development; no configuration was changed.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    raise SystemExit(main())
