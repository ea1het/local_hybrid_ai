Feature: Common installer lifecycle
  The internal installer is manifest-driven and is reached publicly only through
  `./local-ai install`. Planning and execution share the same dependency/lifecycle
  model so a dry-run describes the operation that execution would perform.

  Background:
    Given stack ownership and dependency truth comes from manifests
    And lifecycle commands come from the common lifecycle registry

  Rule: Planning never mutates installation state

    @INSTALL-PLAN-001
    Scenario: Planning is read only
      Given valid manifests and lifecycle definitions
      When an operator requests an install plan through local-ai
      Then the requested stacks and dependency closure are displayed
      And prepare, deploy, ready, reconcile and verify actions are described in order
      And no lifecycle command is executed
      And no runtime, Docker object or protected operational environment is changed

  Rule: Execution converges rather than merely starting containers

    @INSTALL-LIFECYCLE-001
    Scenario: A stack converges through the declared lifecycle
      Given a requested stack and its required dependencies
      When the operator explicitly confirms a real install
      Then PREPARE completes before DEPLOY for previously unprepared stacks
      And required runtime becomes READY before dependent work continues
      And capability reconciliation runs only for consumers affected by this operation or explicitly requested
      And a restart-causing reconcile is followed by another READY convergence
      And lifecycle scripts are executable when invoked directly or are invoked through an explicit interpreter
      And VERIFY is the final stack-owned proof
      And an already stable provider is not spuriously redeployed merely because it was requested

  Rule: Preparation and runtime health are independent facts

    @INSTALL-LOCK-001
    Scenario: Prepared state is not confused with healthy state
      Given a stack has a .lock file
      Then the stack is considered PREPARED only
      And the lock does not prove that containers exist
      And the lock does not prove readiness or application health
      And deployment readiness is determined independently from required runtime state
      And verification remains necessary after deployment or reconciliation
