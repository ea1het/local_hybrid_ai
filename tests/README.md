<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Stack tests

Tests are grouped by stack (`stack_00` through `stack_70`). They exercise every
Python module in the stack directories with temporary files and
mocked external operations; they do not deploy containers or modify a live
server.

Run the complete suite from the repository root:

```sh
python3 tests/run.py
```

`tests/run.py` disables bytecode before importing pytest. For any other Python
runner or for importing modules directly, start Python with `-B` or set
`PYTHONDONTWRITEBYTECODE=1`; a module cannot prevent caching of its own code
after an arbitrary importer has already begun loading it.

These tests do not replace deployment and integration checks against Docker,
host certificates, filesystem ownership, and real provider services.
