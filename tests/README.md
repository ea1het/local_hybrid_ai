# Tests

All automated repository tests live under this directory. Production stacks and the private `commands/` implementation package must not contain `test_*.py` files.

```text
tests/
├── test_*.py                  platform, CLI, install and upgrade contracts
└── disaster_recovery/
    └── test_*.py              disaster-recovery contracts
```

Run the repository suite from the repository root without creating Python caches:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py'
```

Gherkin scenarios under `docs/devel-docs/openspec/` carry stable tags. Where a scenario has direct automated coverage, the corresponding Python test should mention the same identifier in its name or a nearby comment/docstring. New behaviour should normally be specified and traced together with its tests.

Tests may import modules under `commands/` directly because they verify private implementation contracts. That does not make those module paths public APIs; external automation continues to use `./local-ai`.
