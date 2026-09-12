# Tests

All automated repository tests live under this directory. Production stacks, `installer/` and `bkp-dr/` must not contain `test_*.py` files.

```text
tests/
├── test_*.py        installer/platform contracts
└── dr/
    └── test_*.py    disaster-recovery contracts
```

Run the repository suite from the repository root:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Gherkin scenarios in `openspec/` carry stable tags. Where a scenario has direct automated coverage, the corresponding Python test should mention the same identifier in its name or a nearby comment/docstring. New behaviour should normally be specified first, then tested.
