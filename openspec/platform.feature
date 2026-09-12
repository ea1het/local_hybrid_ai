Feature: Atomic platform architecture

  @PLATFORM-DEP-001
  Scenario: Required stack dependencies resolve before the requested stack
    Given stack manifests declare required dependencies
    When the platform resolves an installation plan
    Then every required dependency appears before its consumer

  @PLATFORM-RUNTIME-001
  Scenario: Mutable runtime stays outside Git source
    Given the repository is deployed under STACKS_ROOT
    When a stack prepares persistent state
    Then mutable application state is created under BASE_PATH
    And Git source remains configuration and executable source
