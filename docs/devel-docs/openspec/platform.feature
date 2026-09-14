# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

Feature: Atomic platform architecture
  The platform is a graph of independently owned Docker stacks. Git is the
  project/source truth; each installation owns mutable desired/runtime state.
  Cross-stack behavior is expressed through manifests and capabilities rather
  than hidden orchestration assumptions.

  Rule: Required dependencies are topologically ordered from manifest data

    @PLATFORM-DEP-001
    Scenario: Required stack dependencies resolve before the requested stack
      Given stack manifests declare required dependencies
      And dependency resolution does not rely on hard-coded stack-number exceptions
      When the platform resolves an installation plan
      Then every required dependency appears before its consumer
      And each stack appears at most once in the resolved plan
      And optional capabilities do not become mandatory dependencies

  Rule: Source and mutable installation state have separate ownership

    @PLATFORM-RUNTIME-001
    Scenario: Mutable runtime stays outside Git source
      Given the repository is deployed under STACKS_ROOT
      And BASE_PATH identifies the installation-owned mutable runtime
      When a stack prepares persistent or installation-local state
      Then mutable application state is created under BASE_PATH
      And Git source remains declarative configuration and executable source
      And the protected root operational environment is not rewritten as a hidden prepare side effect
      And installation-local management state is not made upstream project truth
