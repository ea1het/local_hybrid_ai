# Point 10 closeout plan — `local-ai` as the sole management interface

Point 10 is complete only when the public management boundary, state semantics, upgrade safety and disaster-recovery wrappers form one coherent operator contract. Work already qualified on m92p is distinguished from the remaining closeout work below.

## Qualified foundations

The following are already implemented and runtime-qualified:

- `./local-ai` is the sole supported root management entry point.
- The common installer is private at `installer/install.py`; root `install.py` is absent.
- Installer arguments such as `--plan` pass through the public CLI unchanged.
- DR accepts both current `installer/install.py` source and historical backup source containing root `install.py`.
- Human stack identifiers are numeric while JSON preserves stable `stackN` identities.
- `status` exposes desired, deployed, actual and drift as distinct installation states.
- Container version discovery uses the same registry/package as the configured image.
- Compatibility policy is separate from registry availability and from executor capability.
- Explicit upgrade selection is installation-local; `--yes` never auto-selects.
- The guarded executor has a real successful Hermes upgrade qualification.
- Upgrade locking, failure journaling, target-image preflight, READY/reconcile/verify and dependent re-verification are implemented.
- Compatibility policies and installation overrides are qualified, including Dockhand's `major-series` project default.

## Remaining closeout work

### 1. Reconcile installation state and upgrade state

`./local-ai status` remains the installation-state view:

```text
STACK COMPONENT DESIRED DEPLOYED ACTUAL DRIFT
```

`./local-ai upgrade check` should become the update-decision view:

```text
STACK COMPONENT ACTUAL AVAILABLE POLICY SELECTABLE SELECTED VALID
```

`ACTUAL` is the bridge between the two views. `CURRENT` is removed from human output because it currently overloads configured/running meaning. JSON schema v1 should add `actual` as the canonical field while temporarily retaining `current` as a compatibility alias; removing that alias requires a later schema revision.

### 2. Clean policy JSON semantics

A policy `show` action has no previous state transition. `previous_effective_policy` should therefore be emitted only for `set`/`clear` mutations, or be explicitly null if the schema requires the field. The preferred contract is omission on read-only `show` and presence on mutation.

### 3. Bind selection to immutable artifact identity

Selection currently verifies that an exact target tag exists and persists the target version, baseline and policy. The remaining supply-chain/race gap is tag movement between selection and apply. Selection should persist the registry digest observed for the chosen target. Apply must resolve the tag again and reject execution if the digest differs before backup, desired-state mutation or deploy.

The human target remains the registry tag/version; the digest is the immutable execution identity.

### 4. Qualify every public restore wrapper

Exercise the public mappings for `restore plan`, `restore drill`, `restore apply --check-clean-target` and the argument/validation path for `restore resume`. Qualification should use non-destructive/read-only or isolated operations wherever possible. We do not repeat a destructive full restore merely to prove CLI delegation when the underlying DR engine is already qualified.

### 5. Freeze documentation and OpenSpec traceability

The public CLI reference, ADR/SDR, OpenSpec and traceability must match the final state model. Mermaid diagrams and internal links must pass repository documentation checks. No alternate public management path may be documented.

### 6. Final m92p gate

The closeout gate should include repository-layout tests, OpenSpec/traceability tests, management CLI tests, status/upgrade tests, DR wrapper tests and the complete regression suite. Runtime checks should be read-only except where a deliberately selected operation is part of the qualification. There is no need to perform another real component upgrade simply to close the point.

## Closure criterion

Point 10 can be declared closed when the six items above are complete and the final m92p gate is green with a clean Git tree and no generated Python caches. At that point external consumers have one supported interface (`./local-ai`), one coherent state vocabulary, explicit and immutable upgrade intent, and documented recovery operations.
