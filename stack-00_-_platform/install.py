#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Orchestrate the complete Stack 0 setup and write its preparation lock.

The entrypoint runs bootstrap, environment/network preparation, CA
installation, TLS installation, and final read-only verification in order.
Each phase checks the installed state before changing it. A prior lock never
skips the audit and is invalidated if a phase fails. A lock is created or
retained only after every phase succeeds. Importing the module is inert."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True


def main() -> None:
    """Verify an existing installation or prepare, verify, and lock a new one."""
    stack_dir = Path(__file__).resolve().parent
    lock_file = stack_dir / ".lock"
    python = sys.executable
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")

    if lock_file.is_symlink() or (lock_file.exists() and not lock_file.is_file()):
        raise SystemExit(f"unsafe preparation lock: {lock_file}")

    for script in ("00-bootstrap.py", "01-prepare.py", "install-ca-cert.py", "install-tls-certs.py", "verify.py"):
        result = subprocess.run([python, "-B", str(stack_dir / script)], env=environment, check=False)
        if result.returncode:
            if lock_file.is_file() and not lock_file.is_symlink():
                lock_file.unlink()
                print(f"Stack0 audit failed; invalidated stale lock: {lock_file}", file=sys.stderr)
            raise SystemExit(result.returncode)

    if lock_file.is_file():
        print(f"\n== Stack0 verified; existing lock retained: {lock_file}")
        return

    # Hard-link creation fails if the lock already exists, so it cannot overwrite one.
    descriptor, temporary_name = tempfile.mkstemp(prefix=".lock.tmp.", dir=stack_dir)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w") as lock:
            lock.write("stack=stack-00_-_platform\n")
            lock.write(f"prepared_at_utc={datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}\n")
        temporary.chmod(0o644)
        os.link(temporary, lock_file)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"\n== Stack0 PREPARED\n  lock: {lock_file}")


if __name__ == "__main__":
    main()
