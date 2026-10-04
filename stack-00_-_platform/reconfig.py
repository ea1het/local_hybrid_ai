"""Report the platform's reconfiguration boundary without changing host state.

Stack 00 already reconciles its certificates, directories, links, and network
through the repeatable install audit. This command therefore does no work and
never starts or stops a container.
"""

import sys

sys.dont_write_bytecode = True


def main() -> int:
    print("Stack 00 has nothing to reconfigure; ./local-ai stack-00 install already reconciles it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
