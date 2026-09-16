# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# Purpose: define externally observable behaviour of the sole supported management
# boundary. Scenarios describe operator/automation contracts, not Python module or
# Docker Compose implementation details.
#
# Architecture: ADR-0002 establishes the single CLI boundary and ADR-0005 places
# its private implementation under commands/. Stack dependency/capability truth
# remains in manifests and is summarized in docs/stacks/README.md.
#
# Evidence: stable tags are mapped to automated and runtime evidence in
# docs/devel-docs/openspec/traceability.md.
Feature: Single management CLI anticorruption boundary
  `./local-ai` is the only supported management surface. Human operators and
  machine consumers reach the same domain operations through that boundary;
  implementation paths remain private and refactorable.

  Rule: External consumers do not couple to implementation paths

    @CLI-BOUNDARY-001
    Scenario: External automation inspects upgrades without internal coupling
      When the consumer runs "./local-ai --json upgrade"
      Then it receives a versioned machine-readable response
      And the response identifies the command and success state
      And stack identity remains stable for machine consumption
      And the consumer does not need the path of any Python, shell, Compose or stack implementation

    @CLI-LAYOUT-001
    Scenario: Private management implementation has one coherent package root
      Given `./local-ai` is the sole supported management boundary
      Then installation, status and upgrade implementation live under `commands/`
      And disaster-recovery implementation lives under `commands/recovery/`
      And no top-level `internal/`, `installer/` or `bkp-dr/` implementation root is required
      And historical recovery paths may be recognized only for restoring recorded source revisions

  Rule: Machine consumers receive stable management envelopes

    @CLI-JSON-001
    Scenario: Install exposes a structured machine contract without publishing implementation commands
      When the consumer runs "./local-ai --json install ..."
      Then the response identifies schema version, command and success state
      And requested and dependency-resolved stacks use stable stackN identities
      And lifecycle actions expose stack, phase and reason rather than private command lines
      And real execution remains confirmation-gated

    @CLI-JSON-002
    Scenario: Restore actions use one public JSON envelope
      When the consumer runs a supported "./local-ai --json restore ..." action
      Then the response identifies schema version, restore action and success state
      And successful private recovery output is nested as the action result
      And private stderr or invalid private JSON is converted to a stable public error response

    @CLI-DOCTOR-001
    Scenario: Doctor diagnoses management prerequisites without mutation
      When the operator runs "./local-ai doctor" or "./local-ai --json doctor"
      Then repository lifecycle metadata is validated
      And protected operational configuration permissions are checked
      And Docker and Compose availability are checked
      And runtime-root absence is diagnostic information rather than an implicit creation request
      And the command does not prepare, deploy, reconcile, restore or upgrade a stack

  Rule: Selective runtime lifecycle preserves dependency and state ownership

    @CLI-RUNTIME-001
    Scenario: A leaf stack can be stopped and started without destructive recreation
      Given the stack is PREPARED and its required providers are running
      When the operator stops and later starts that stack through `./local-ai`
      Then stop uses non-destructive runtime stop semantics
      And the stack-owned containers remain present while stopped
      And start reuses the existing stack runtime rather than recreating it implicitly
      And start waits for the stack's required runtime to become READY

    @CLI-RUNTIME-002
    Scenario: Runtime lifecycle fails closed across required dependencies
      Given a provider has a running required consumer
      When the operator attempts to stop the provider through `./local-ai`
      Then the operation fails before Compose mutation
      And the required consumer remains running
      And when a consumer is started with a required provider not running
      Then the operation fails rather than implicitly starting that provider

  Rule: Upgrade discovery is inventory, not consent

    @CLI-REGISTRY-001
    Scenario: Registry failures remain unknown rather than becoming current
      Given registry discovery receives rate-limit, unauthorized or forbidden status
      When upgrade inventory is rendered
      Then the remote status remains rate_limited, unauthorized or forbidden respectively
      And available is unknown
      And the component is never described as current from failed remote evidence

    @CLI-REGISTRY-002
    Scenario: Repeated registry discovery uses a bounded expiring cache
      Given upgrade inventory has recently resolved a component against its configured registry package
      When the same component and local immutable image identity are checked again inside the configured TTL
      Then the cached registry state may be reused
      And a changed local digest produces a cache miss
      And expired entries produce a cache miss
      And the cache retains only a bounded number of entries
      And disabling the cache never changes registry-discovery semantics

    @CLI-UPGRADE-001
    Scenario: Upgrade shows the complete component inventory
      When the operator runs "./local-ai upgrade"
      Then every declared component of every stack is represented
      And the human contract contains Installed, Available, Policy, Selectable, Selected and Valid columns
      And Installed is the concrete runtime observation
      And registry discovery alone does not create a selection
      And an unavailable or failed registry lookup is not silently reported as current
      And "./local-ai upgrade check" remains a compatibility alias

    @CLI-UPGRADE-007
    Scenario: Upgrade inventory explains execution safety for every component
      When upgrade inventory is rendered for machine consumption
      Then every component exposes explicit execution metadata
      And selectable components declare guarded execution
      And non-selectable components identify why execution is blocked
      And discovery of a newer artifact never bypasses that execution gate

    @CLI-UPGRADE-008
    Scenario: Selectable is the result of executor qualification
      Given a component is marked selectable
      Then its upgrade path has explicit identity and compatibility rules
      And its version-authority mutation and deployment scope are defined
      And applicable migration and recovery behaviour are defined
      And READY and VERIFY conditions are defined
      And dependency impact is understood
      And automated failure and success tests exist
      And the path has passed representative runtime qualification
      And changing compatibility policy alone cannot make an unqualified component selectable

    @CLI-UPGRADE-002
    Scenario: Selecting a version changes only the local upgrade plan
      Given the component is selectable
      And the exact target exists in the configured registry package
      And the target satisfies the current effective compatibility policy
      When the operator selects a version for the component
      Then the selection is persisted in the installation runtime area
      And the current runtime version is recorded as the selection baseline
      And the policy used for selection is recorded for traceability
      And the exact target image and immutable registry digest are recorded
      And no container or desired version key is changed

    @CLI-UPGRADE-003
    Scenario: Yes never means upgrade everything
      Given one or more component versions are selected
      And other components may have newer registry artifacts available
      When the operator runs "./local-ai upgrade --yes"
      Then only selected components may be considered by the executor
      And unselected available versions are never implicitly selected
      And confirmation does not broaden the installation's desired upgrade intent

    @CLI-UPGRADE-004
    Scenario: A stale selection is rejected before mutation
      Given a component was selected from a recorded current version
      And the actual runtime version changed afterwards
      When the operator runs "./local-ai upgrade --yes"
      Then execution fails with UPGRADE_PLAN_STALE
      And no recovery point is created
      And no desired version key is changed
      And no target deployment is started

    @CLI-UPGRADE-005
    Scenario: A selected component upgrades through the guarded lifecycle
      Given a selected component declares a safe targeted deploy method
      And the selection still satisfies selectability, baseline and effective policy
      When the operator confirms with "./local-ai upgrade --yes"
      Then a recovery point is created first when the component requires one
      And only explicitly selected version keys are changed
      And only the selected component deployment is targeted
      And the selected component reaches READY before reconciliation-dependent verification
      And stack VERIFY passes
      And prepared dependent consumers affected by dependency or capability relationships are reverified
      And the selection is cleared only after success
      And successful execution is appended to upgrade history
      And human success is reported as "UPGRADE: PASS"

    @CLI-UPGRADE-006
    Scenario: Exact target images are proven before mutation
      Given one or more container-image components are selected
      When the operator runs "./local-ai upgrade --yes"
      Then every exact selected image reference is checked with a read-only registry manifest inspection
      And an unavailable target fails before recovery or desired-state mutation
      And the observed digest must equal the immutable digest recorded at selection
      And a moved tag fails with UPGRADE_TARGET_MOVED
      And all target-image preflights complete before a recovery point is created
      And the operational environment is not changed before all target-image preflights pass

    @CLI-UPGRADE-009
    Scenario: Absence of PASS is not a successful upgrade
      When guarded upgrade execution fails at any required preflight, mutation, READY, reconciliation or VERIFY step
      Then "UPGRADE: PASS" is not emitted
      And a recovery point is reported when one was created before the failure
      And the operator must not infer success merely because a container is running
      And successful upgrade history is not appended unless the guarded operation completes

    @CLI-UPGRADE-010
    Scenario: An administrator may explicitly accept an unqualified upgrade path
      Given a component is not selectable
      And the catalog already defines a deterministic version-authority mutation and targeted deploy recipe
      When the administrator selects an exact target with "--force"
      Then the selection records that project qualification was bypassed
      And the catalog remains non-selectable
      And policy, target existence and immutable digest validation still apply
      And apply revalidates stale runtime, recovery, READY, VERIFY and dependency-impact gates
      And successful history preserves that the operation was forced
      And a component without a deterministic mutation recipe fails with UPGRADE_FORCE_UNAVAILABLE

  Rule: Operational status is distinct from version maintenance and environment diagnosis

    @CLI-STATUS-001
    Scenario: Human status summarizes stack operation without duplicating upgrade inventory
      When the operator runs "./local-ai status"
      Then exactly one operational row is rendered for each declared stack
      And the human contract contains Stack, Name, State, Health and Drift columns
      And State is derived from preparation and required runtime container state
      And Health reports generic runtime readiness rather than registry update availability
      And Drift aggregates component installation drift for the stack
      And Desired, Deployed, Actual, Installed and Available are not human status columns
      And version maintenance remains the responsibility of "./local-ai upgrade"
      And management prerequisite diagnosis remains the responsibility of "./local-ai doctor"

    @CLI-STATUS-002
    Scenario: Automation retains detailed diagnostic component state
      When the consumer runs "./local-ai --json status"
      Then it receives status schema version 3
      And the response contains stack operational records and detailed component records
      And every stack record contains state, health and drift
      And every component record contains desired, deployed, actual and drift
      And drift uses only yes, no or n/a
      And stack identifiers use stable stackN machine identities
      And runtime state is not synthesized from desired configuration

    @CLI-STATUS-003
    Scenario: Shared component identity remains fail-closed for mutable tags
      Given a component may use a mutable container tag such as alpine, latest, major-only or major.minor tracking
      When management evaluates configured and observed component identity
      Then a moved mutable tag is reported as drift yes when local and remote identities differ
      And an unchanged mutable tag is reported as drift no only when registry identity evidence proves equality
      And a registry lookup failure never becomes a false drift no
      And fixed semantic tags do not require remote registry resolution merely to compare equal fixed identities
      And digest-pinned images compare their immutable digest identities directly
      And status and upgrade consume the same low-level image identity semantics rather than independent parsers
