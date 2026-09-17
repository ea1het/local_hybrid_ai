# Command package architecture

`./local-ai` is the only public management interface.

Public command ownership is split into independent packages:

- `install/`
- `backup/`
- `restore/`
- `status/`
- `doctor/`
- `inventory/`
- `completion/`
- `upgrade/`
- `lifecycle/` owns the global/per-stack `start` and `stop` operations.

`--json` and `--yes` belong to the public CLI boundary and are represented by `CommandContext`; command packages receive semantic state, not private copies of those public flags.

## Dependency rule

A command package must not depend on another command package. If two commands need the same installation/runtime primitive, that primitive must live outside both command domains. Shared infrastructure is introduced only when an actual shared dependency exists; there is deliberately no broad `core` package.

Tests that describe one command's private behavior live below that command package. Repository-level `tests/` is reserved for the public CLI contract and genuinely cross-command invariants.

`status` is operational only: stack identity, runtime state and health. Version intent, deployed/current/available identities, drift, registry discovery, selection, policy and targets belong to `upgrade`.
