Feature: Single management CLI anticorruption boundary
  `./local-ai` is the only supported management surface. Human operators and
  machine consumers reach the same domain operations through that boundary;
  implementation paths remain private and refactorable.

  Rule: External consumers do not couple to implementation paths

    @CLI-BOUNDARY-001
    Scenario: External automation inspects upgrades without internal coupling
      When the consumer runs "./local-ai --json upgrade check"
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

  Rule: Upgrade discovery is inventory, not consent

    @CLI-UPGRADE-001
    Scenario: Upgrade check shows the complete component inventory
      When the operator runs "./local-ai upgrade check"
      Then every declared component of every stack is represented
      And the current human contract contains Actual, Available, Policy, Selectable, Selected and Valid columns
      And Actual is the runtime observation shared with status
      And registry discovery alone does not create a selection
      And an unavailable or failed registry lookup is not silently reported as current

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
    Scenario: A selected stateful component upgrades through the guarded lifecycle
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

  Rule: Installation state distinguishes intent, history and runtime reality

    @CLI-STATUS-001
    Scenario: Component intent and runtime reality remain distinct
      When the operator runs "./local-ai status"
      Then every declared component reports Desired, Deployed and Actual independently
      And Desired comes from installation-owned configuration
      And fixed desired image identities remain fixed version or digest identities
      And mutable tracking tags are resolved through the same owning registry used by upgrade discovery when possible
      And Deployed is the latest successfully recorded guarded upgrade when known
      And a component without guarded-upgrade history adopts its observed concrete runtime version as the pre-history deployment baseline
      And versioned deployment that does not apply is represented as n/a rather than unknown
      And Actual comes from the observed runtime image
      And a mutable runtime tag is displayed as its concrete registry-mapped running version when that mapping is available
      And Drift compares Desired with Actual
      And Drift is yes when Desired and Actual differ
      And Drift is no when Desired and Actual match
      And Drift is n/a when drift is not meaningful or a mutable-tag comparison cannot be proven
      And equal mutable tag strings alone never prove no drift
      And an upgrade selection is not treated as desired or deployed state

    @CLI-STATUS-002
    Scenario: Automation consumes component state without internal coupling
      When the consumer runs "./local-ai --json status"
      Then it receives status schema version 2
      And every component contains desired, deployed, actual and drift fields
      And drift uses only yes, no or n/a
      And stack identifiers use stable stackN machine identities
      And runtime state is not synthesized from desired configuration

    @CLI-STATUS-003
    Scenario: Registry-backed status cannot regress to tag-text equality
      Given a component may use a mutable container tag such as alpine, latest, major-only or major.minor tracking
      When status evaluates Desired and Actual
      Then a moved mutable tag is reported as drift yes when local and remote identities differ
      And an unchanged mutable tag is reported as drift no only when registry identity evidence proves equality
      And a registry lookup failure never becomes a false drift no
      And fixed semantic tags do not require remote registry resolution merely to compare equal fixed identities
      And digest-pinned images compare their immutable digest identities directly
      And the concrete Actual shown by status matches the concrete Actual shown by upgrade check for the same registry-backed runtime
