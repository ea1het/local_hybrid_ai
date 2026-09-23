# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

Feature: Disaster recovery
  Disaster recovery reconstructs the installation from a completed recovery point,
  the source revision recorded by that point and explicitly external prerequisites.
  Runtime existence alone does not make data durable and raw directory copying is
  not a substitute for a stack's declared recovery strategy.

  Rule: Publication produces one internally consistent recovery point

    @DR-BACKUP-001
    Scenario: A global backup publishes one atomic recovery point
      Given deployed stacks declare recovery resources and prerequisites
      And required external prerequisites are valid before publication
      And the protected operational environment is available as a sensitive global artifact
      When the operator runs backup all through the supported management interface
      Then one immutable backup set is published atomically
      And every declared artifact is covered by the checksum index
      And the recorded source commit identifies the source used for reconstruction
      And sensitive metadata contains no secret values
      And a partially produced staging set is never presented as a completed recovery point

    @DR-BACKUP-002
    Scenario: A backup destination cannot overlap installation source or runtime
      Given STACKS_ROOT and BASE_PATH identify the live installation source and mutable runtime
      When the operator chooses a backup destination
      Then the resolved destination must be outside STACKS_ROOT
      And the resolved destination must be outside BASE_PATH
      And the destination must not be an ancestor of STACKS_ROOT or BASE_PATH
      And equivalent paths expressed through dot-dot or symbolic-link resolution are rejected
      And overlap rejection happens before backup staging or publication mutates the destination

  Rule: Restore follows resource strategy and dependency order

    @DR-RESTORE-001
    Scenario: Recovery uses declared strategies instead of raw runtime copying
      Given a completed recovery point with valid checksums
      When restore planning resolves the platform
      Then reconstructable stacks are rebuilt from the recorded source
      And managed data uses its declared recovery adapter
      And externalized data is verified or re-provisioned through its declared prerequisite
      And protected operational configuration is restored before lifecycle operations that consume it
      And destructive clean-target execution requires explicit confirmation
      And recovery fails closed when a required source, artifact or external prerequisite cannot be proven

  Rule: Isolated drills prove durable application state without touching live runtime

    @DR-STACK7-001
    Scenario: Open WebUI persistent state can be restored in isolation
      Given a Stack7-aware global recovery point
      And the drill destination is separate from the live BASE_PATH
      When open-webui-data is restored using the DR archive contract
      Then users chats configuration model policy and access grants are present
      And archive extraction obeys path and ownership safety checks
      And drill containers do not publish platform ports or join the live platform network
      And the live Open WebUI runtime is not modified
