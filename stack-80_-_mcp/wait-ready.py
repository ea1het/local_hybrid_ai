# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Check readiness inside selected containers; does not authorize Google."""

import time

from stack_env import compose, parser, selected


def main():
    options = parser(__doc__)
    options.add_argument("--timeout", type=float, default=60)
    args = options.parse_args()
    if not 0 < args.timeout < float("inf"):
        options.error("--timeout must be a positive finite number")
    pending = set(selected(args))
    deadline = time.monotonic() + args.timeout
    while pending and time.monotonic() < deadline:
        for service in sorted(pending):
            try:
                compose("exec", "-T", service, "curl", "--fail", "--silent",
                        "--max-time", "2", "http://127.0.0.1:8000/health/ready")
            except RuntimeError:
                continue
            pending.remove(service)
            print(f"{service}: ready; Google authorization is a separate check.")
        if pending:
            time.sleep(min(2, max(0, deadline - time.monotonic())))
    if pending:
        raise SystemExit("Not ready before timeout: " + ", ".join(sorted(pending)))


if __name__ == "__main__":
    try:
        main()
    except OSError as error:
        raise SystemExit(str(error))
