# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Load stack entrypoints as package members for isolated behavioral tests.

Operational filenames retain CLI-oriented hyphens and numeric prefixes, so
ordinary import statements cannot name them. The helper loads each script
by path beneath its real stack package, enabling package-relative helper
imports while leaving direct CLI execution intact. Merely importing this
module does not load an operational script or touch host state."""

import importlib
import importlib.util
import sys

sys.dont_write_bytecode = True
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(stack: str, filename: str):
    """Load a script with its stack package as the parent namespace."""
    path = ROOT / stack / filename
    qualified = filename.removesuffix(".py").replace("/", "_").replace("-", "_")
    sys.path.insert(0, str(ROOT))
    try:
        importlib.import_module(stack)
    finally:
        sys.path.pop(0)
    name = f"{stack}._test_{qualified}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
