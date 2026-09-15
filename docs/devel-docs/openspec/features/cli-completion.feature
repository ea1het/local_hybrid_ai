# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

Feature: Source-local shell completion
  Bash and Zsh completion must expose the current CLI topology without creating
  a second component authority or crossing runtime and registry boundaries.

  @CLI-COMPLETION-001
  Scenario: Component completion follows manifest inventory
    Given stack manifests declare the current component topology
    When the operator requests TAB completion for an upgrade stack
    Then completion candidates are derived from the compiled manifest inventory
    And no separate static component list is required

  @CLI-COMPLETION-002
  Scenario: Completion has no runtime or network side effects
    When Bash or Zsh asks local-ai for completion candidates
    Then the completion path does not inspect Docker runtime state
    And it does not query remote registries
    And it does not mutate runtime state or the operational environment

  @CLI-COMPLETION-003
  Scenario: Bash and Zsh adapters use the same completion semantics
    When the operator runs local-ai completion for Bash or Zsh
    Then the generated shell adapter delegates candidates to the private completion endpoint
    And invalid source inventory makes completion fail quietly in the interactive shell
