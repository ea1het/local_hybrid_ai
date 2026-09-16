<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Current implementation state

[← Documentation map](TOC.md) · [Management-plane architecture](architecture/management-plane.md) · [Stack architecture](stacks/README.md)

This page describes the implementation that exists in the current source tree. It is not a roadmap or chronology. Superseded designs are mentioned only where necessary to prevent use of a retired interface.

## Management boundary

`./local-ai` is the only supported management interface. Current public command families are installation/lifecycle (`install`, `start`, `stop`), operational inspection (`status`, `doctor`, `inventory rescan`), version maintenance (`upgrade`, `upgrade policy`, `upgrade adopt`), recovery (`backup`, `restore plan`, `restore drill`, `restore apply`, `restore resume`) and shell integration (`completion bash`, `completion zsh`, `completion install`, `completion status`).

Implementation lives under `commands/`, with recovery implementation under `commands/recovery/`. Stack-owned scripts are implementation details behind that boundary. The internal architecture deliberately separates lifecycle planning, upgrade observation/selection/execution and recovery preflight/restore phases so that read-only decisions and mutating operations remain auditable. The [management-plane architecture](architecture/management-plane.md) describes these responsibility boundaries without promoting private Python modules to public APIs.

## Stack and component model

The platform contains eight independently owned stacks, 0 through 7. Stack0 is the common foundation. Stack6 and Stack7 require Stack3. Stack2 capabilities are optional to AI consumers.

Operational component topology is manifest-driven. Each stack `manifest.json` declares physical ownership in `owns[]` and operational semantics in `components[]`. Components are classified `versioned`, `local`, `helper` or `platform`. Compose binds semantic components to concrete services but is not a second catalog.

The manifest system separates general graph/capability semantics from recovery-specific validation. This keeps dependency planning and recovery safety related through the same declarations without collapsing them into one validation responsibility.

`inventory rescan` produces a diagnostic topology snapshot and source fingerprint. The snapshot is history/evidence only; normal management compiles current manifests directly.

## Source, runtime and version authority

Git contains the bootstrap/source baseline. Mutable installation state is installation-owned and outside the source checkout. PREPARE does not silently regenerate the protected operational `.env`.

For versioned components the internal model distinguishes **desired** (installation-owned exact intent; exact Compose fallback before adoption), **deployed** (last confirmed deployment/adoption baseline), **actual** (concrete runtime identity), **available** (registry discovery only) and **drift** (desired versus actual disagreement).

Human views are deliberately simpler: `status` answers whether stacks are operational/coherent; `upgrade` is the normal version-maintenance view. Registry discovery never becomes desired state or consent. Older installations use non-disruptive `upgrade adopt` to record already-running identities.

## Upgrade execution

A target must be selected explicitly before `upgrade --yes` can mutate runtime. Compatibility policy and project qualification are separate gates. A normally selectable component has a qualified guarded executor. An inventory-only component remains non-selectable unless an administrator uses `--force` and a deterministic mutation recipe exists. Force bypasses qualification only, not target/digest validation, compatibility, stale-plan checks, recovery, READY/VERIFY or consumer checks.

The refactored upgrade implementation keeps command orchestration, selection/stale-plan decisions, inventory/catalog state, runtime observation, OCI registry handling and guarded mutation as separate responsibilities. Runtime image/version and OCI identity primitives are shared instead of being reimplemented inside the executor. These are internal maintainability boundaries; external consumers continue to use `./local-ai`.

Registry failures are fail-closed: rate limiting, authorization failure or indeterminate latest-only ordering produce unknown availability, never false `current`.

## Lifecycle

The lifecycle is `PREPARE → DEPLOY → READY → RECONCILE → VERIFY`. A stack `.lock` means PREPARED only. Selective `stop` refuses to break active required consumers; selective `start` does not invent or auto-start missing providers.

## Shell completion

TAB completion is manifest-aware and source-local. Candidate calculation does not query Docker or registries. Bash/Zsh adapters can be generated without mutation. `completion install` detects the shell from `$SHELL`, chooses the implemented root/user target, writes the generated adapter idempotently and does not rewrite shell startup files. `completion status` verifies the target file/content. Actual loading still depends on the shell's own completion configuration (`bash-completion` for the Bash user directory; `fpath`/completion initialization for Zsh), so installed-file state is not claimed as proof that every interactive shell loads it. Candidate-grammar discrepancies, when present, are tracked in [pending work](pending.md) rather than being presented as completed behaviour.

## Disaster recovery

Recovery is manifest-driven. The protected operational `.env` is a sensitive global artifact. Stack0 PKI, Stack3 logical database state, Stack4 native Gitea state and Stack7 Open WebUI data are managed recovery artifacts. Stack6 runtime is reconstructable; durable user memory is Git-backed. Stack4 runner runtime/registration is reconstructable and is not a managed recovery resource.

Recovery planning/orchestration and read-only destination/runtime-source preflight are now separate implementation responsibilities. Backup execution, restore staging, managed-state restore, live-state application and resume verification remain explicit phases because they have different mutation and safety properties. Backup destinations equal to, inside, or ancestors of protected source/runtime roots are rejected. Restore planning, drills, clean-target apply and resumable recovery are explicit operations rather than lifecycle side effects.

## Retired implementation surfaces

The following are not current architecture: separate top-level `internal/`, `installer/` and `bkp-dr/` roots; static `commands/upgrade-components.json`; Git/Compose as ongoing version authority after adoption; `tracked-compose-pin` as a generic upgrade blocker; registry discovery as implicit selection; and direct stack scripts/Compose/Python modules as supported external management APIs.

Historical ADRs, compatibility code and tests may mention retired paths only to explain decisions or recover older recorded source revisions. Those references are historical evidence, not current interfaces.

## Evidence boundary

Repository tests prove deterministic source contracts. Runtime qualification is required for behaviours depending on real Docker, registries or applications. The current management refactor was validated by the repository test suite before integration, but that source-level evidence does not replace runtime qualification for environment-dependent behaviour. See [developer testing](devel-docs/testing.md) and [OpenSpec traceability](devel-docs/openspec/traceability.md).
