<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Component version authority

[← User documentation](README.md) · [CLI reference](cli.md) · [ADR-0006](../devel-docs/adr/0006-operational-version-authority.md)

Local Hybrid AI separates source defaults, installation intent, observed runtime and registry availability.

- Git-tracked Compose provides exact source baselines for a fresh installation.
- The protected operational `.env` carries installation-owned image/version overrides after adoption.
- Docker runtime provides the observed `ACTUAL` state.
- Registry discovery provides `AVAILABLE`; it does not silently change `DESIRED`.

## Adopt an existing installation

Existing deployments that predate operational image authority can record the exact already-running baseline without recreating any container.

```bash
./local-ai upgrade adopt
sudo ./local-ai upgrade adopt --yes
```

The first command is read-only and prints the identities that would be adopted plus the missing operational keys. The second command writes only missing non-secret image/version keys to the protected root `.env` atomically. Existing values must already agree with the running installation; a conflict fails closed and nothing is overwritten implicitly.

Adoption does **not** pull images, run Compose, select an upgrade or restart a service.

After successful adoption, `./local-ai status` should report installation-owned `DESIRED` values rather than following moving registry channels. `./local-ai upgrade check` may still report newer `AVAILABLE` versions independently.

## Guarded upgrades

A component becomes selectable only when its executor has been explicitly qualified. Externalizing version authority does not by itself authorize mutation. HAProxy and Stack2 Redis use the generic guarded repository/version executor. Stateful or migration-sensitive components remain inventory-only until their compatibility and migration contracts are explicit.

For example, after adoption:

```bash
./local-ai upgrade stack2 redis select 8.10.1-alpine3.23
sudo ./local-ai upgrade --yes
```

Selection validates policy and immutable registry identity. Apply mutates only the installation-owned version key, performs targeted deployment, waits for READY and verifies the selected version. Registry discovery alone never creates consent.
