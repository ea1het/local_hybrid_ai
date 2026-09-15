# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

Feature: Persistent shell completion installation
  The management CLI may persist its shell adapter only through an explicit
  operator command, while candidate calculation remains source-local.

  Scenario: Detect a supported shell
    Given the operator shell is Bash or Zsh
    When the operator runs completion install
    Then local-ai installs the matching generated completion adapter
    And repeated installation is idempotent

  Scenario: Reject an unsupported shell
    Given the operator shell is not Bash or Zsh
    When the operator runs completion install
    Then local-ai fails without guessing a shell target

  Scenario: Preserve operator startup configuration
    When completion install selects a persistent target
    Then local-ai writes only the completion adapter
    And local-ai does not rewrite shell startup files
