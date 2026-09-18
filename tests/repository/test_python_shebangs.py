#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Keep the project shebang mandatory and explicit across Python modules."""

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class PythonShebangContractTests(unittest.TestCase):
    """Verify every tracked Python module starts with the project shebang."""

    def test_tracked_python_modules_have_a_shebang(self):
        """Delegate classification to the same conservative repository policy."""
        result = subprocess.run(
            [sys.executable, "tools/apply_python_shebangs.py", "--check"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
