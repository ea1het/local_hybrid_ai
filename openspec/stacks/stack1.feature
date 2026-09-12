Feature: Stack1 ingress

  @STACK1-INGRESS-001
  Scenario: User-facing HTTP enters through HAProxy
    Given an application is configured for ingress
    Then HAProxy reaches it over redlocal
    And the application does not require a direct host port
