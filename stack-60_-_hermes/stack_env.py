# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Read the stack's simple shell assignment file without executing it."""

import os
import sys

sys.dont_write_bytecode = True
import re
import shlex
from pathlib import Path


ASSIGNMENT = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
VARIABLE = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")


def strip_comment(raw: str) -> str:
    quote = None
    escaped = False
    for index, character in enumerate(raw):
        if escaped:
            escaped = False
        elif character == "\\" and quote != "'":
            escaped = True
        elif character == quote:
            quote = None
        elif quote is None and character in ("'", '"'):
            quote = character
        elif quote is None and character == "#" and index > 0 and raw[index - 1].isspace():
            return raw[:index].rstrip()
    return raw


def load_env(path: Path) -> dict[str, str]:
    values = dict(os.environ)
    for number, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = ASSIGNMENT.fullmatch(line)
        if not match:
            raise ValueError(f"unsupported .env syntax at {path}:{number}")
        key, raw = match.groups()
        if "$(" in raw or "`" in raw or "\\$" in raw:
            raise ValueError(f"shell command expansion is not supported at {path}:{number}")
        raw = strip_comment(raw)
        if raw.startswith("'") and raw.endswith("'") and raw.count("'") == 2:
            values[key] = raw[1:-1]
            continue
        if "'" in raw:
            raise ValueError(f"unsupported .env quoting at {path}:{number}")
        tokens = shlex.split(raw, comments=False)
        if len(tokens) > 1:
            raise ValueError(f"unsupported .env value at {path}:{number}")
        value = tokens[0] if tokens else ""
        value = VARIABLE.sub(lambda found: values.get(found.group(1) or found.group(2), ""), value)
        if "$" in value:
            raise ValueError(f"unsupported .env expansion at {path}:{number}")
        values[key] = value
    return values
