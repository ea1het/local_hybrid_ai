<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Stack tests

[Reading guide](../README.md#reading-guide) · Next: [Pending work](../pending.md)

`stack_00` … `stack_70` test each stack's Python modules. The top-level
`test_*.py` files cover the shared pieces: the `local-ai` dispatcher and shell
completion, the wrappers, `status`, `env bootstrap`, the progress bar, Compose
healthchecks, MPL headers, shebangs, and the absence of `__pycache__`. All
tests use temporary files and mocked external operations; they do not deploy
containers or modify a live server.

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

## Importing stack packages

Each existing `stack-NN_-_*` directory is a Python package. The filesystem
names remain unchanged because Compose files, deployment paths, and operator
commands depend on them. Since hyphens and numeric script prefixes are not
valid in a Python `import` statement, use `importlib` from the repository root:

```python
import importlib

platform = importlib.import_module("stack-00_-_platform")
prepare = importlib.import_module("stack-00_-_platform.01-prepare")
```

Package imports do not execute operational `main()` functions. Direct script
execution, such as `./stack-00_-_platform/01-prepare.py`, remains supported.
Use `python3 -B` (or `PYTHONDONTWRITEBYTECODE=1`) when importing from a fresh
interpreter if the checkout must remain free of bytecode files.
