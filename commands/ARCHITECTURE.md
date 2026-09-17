# Command package architecture

`./local-ai` is the only public management interface.

Public command ownership is split into independent packages: `install/`, `backup/`, `restore/`, `status/`, `doctor/`, `inventory/`, `completion/`, `upgrade/`; `lifecycle/` owns global/per-stack `start` and `stop`.

`--json` and `--yes` belong to the public CLI boundary and are represented by `CommandContext`; command packages receive semantic state, not private copies of those public flags.

## Dependency rule

A command package must not depend on another command package. Shared installation/runtime primitives live in `commands/installer.py`; this is a narrow infrastructure module, not a generic `core`. In particular, `commands.install` exposes only the install command API and must not re-export installer primitives for other commands.

Tests that describe one command's private behavior live below that command package. Tests for the shared installer infrastructure live at repository level because that infrastructure is consumed by multiple command domains.

`status` is operational only: stack identity, runtime state and health. Version intent, deployed/current/available identities, drift, registry discovery, selection, policy and targets belong to `upgrade`.
