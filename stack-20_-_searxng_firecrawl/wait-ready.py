#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import os
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
import time
from pathlib import Path

STACK_DIR = Path(__file__).resolve().parent
ENV_FILE = STACK_DIR / ".env"
LOCK_FILE = STACK_DIR / ".lock"
TCP_PROBE = '''
const net = require("net");
const host = process.argv[1];
const port = Number(process.argv[2]);
const socket = net.createConnection({host, port});
const finish = (ok) => { socket.destroy(); process.exit(ok ? 0 : 1); };
socket.setTimeout(1500);
socket.once("connect", () => finish(true));
socket.once("timeout", () => finish(false));
socket.once("error", () => finish(false));
'''


def log(message):
    print(f"[stack2-ready] {message}")


def die(message):
    print(f"[stack2-ready] ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def running(name):
    result = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", name],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return result.returncode == 0 and result.stdout.rstrip(b"\n") == b"true"


def tcp_ready(host, port):
    return subprocess.run(["docker", "exec", "firecrawl-api", "node", "-e", TCP_PROBE, host, port],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def main():
    timeout = os.environ.get("STACK2_READY_TIMEOUT_SECONDS") or "90"
    if os.geteuid() != 0:
        die("run as root")
    if shutil.which("docker") is None:
        die("docker is not installed")
    if not ENV_FILE.is_file():
        die(f"missing {ENV_FILE}")
    if not LOCK_FILE.is_file():
        die("Stack2 is not PREPARED")
    if not re.fullmatch(r"[0-9]+", timeout):
        die("STACK2_READY_TIMEOUT_SECONDS must be an integer")
    start = int(time.time())
    while True:
        if running("searxng") and running("firecrawl-api") and tcp_ready("searxng", "8080") and tcp_ready("firecrawl-api", "3002"):
            log("web.search endpoint searxng:8080: READY")
            log("web.extract endpoint firecrawl-api:3002: READY")
            return
        if int(time.time()) - start >= int(timeout):
            die(f"Stack2 capability endpoints did not become ready within {timeout}s")
        time.sleep(1)


if __name__ == "__main__":
    main()
