# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

Feature: Stack4 Git service
  Stack4 owns the local Gitea service and its repositories. Gitea uses SQLite in
  this installation, but disaster recovery treats the application as a managed
  service and uses its native dump rather than copying a potentially live database.

  @STACK4-GIT-001
  Scenario: Gitea durable state is recoverable without raw filesystem database backup
    Given Gitea is deployed with repositories and application state
    When a DR backup is created
    Then Stack4 uses a controlled native Gitea dump
    And the backup contains database and repository content required by the recovery contract
    And the live SQLite database is not treated as a safe raw-copy artifact
    And isolated recovery reconstructs the SQLite database from the dump
    And repository integrity can be verified with git fsck
    And Stack6 memory recovery does not assume that its configured Git remote must be this Gitea instance
