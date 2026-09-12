Feature: Stack7 Open WebUI

  @STACK7-POLICY-001
  Scenario: A regular user receives the curated default model
    Given the first administrator exists
    When Stack7 model policy is reconciled
    Then basic_autorouter is active
    And basic_autorouter has public read access
    And Arena is disabled
    And a regular user sees only the curated public model

  @STACK7-WEB-001
  Scenario: New chats start with web search enabled
    Given Stack7 persistent configuration is initialized
    Then basic_autorouter is the default model
    And web search is active by default
    And the user can disable it per chat
