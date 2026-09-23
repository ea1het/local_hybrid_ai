# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

Feature: Shell completion installation
  The management CLI may install its shell adapter only through an explicit
  operator command, while candidate calculation remains source-local. Writing
  the adapter does not imply that every shell configuration loads its target.

  @CLI-COMPLETION-004
  Scenario: Detect a supported shell and install its adapter
    Given the operator shell is Bash or Zsh
    When the operator runs completion install
    Then local-ai writes the matching generated completion adapter to its selected target
    And repeated installation is idempotent

  @CLI-COMPLETION-005
  Scenario: Reject an unsupported shell
    Given the operator shell is not Bash or Zsh
    When the operator runs completion install
    Then local-ai fails without guessing a shell target

  @CLI-COMPLETION-006
  Scenario: Preserve operator startup configuration
    When completion install selects an adapter target
    Then local-ai writes only the completion adapter and required parent directory
    And local-ai does not rewrite shell startup files
