Feature: Stack3 AI gateway

  @STACK3-GATEWAY-001
  Scenario: Applications consume one OpenAI-compatible gateway
    When Stack3 is running
    Then LiteLLM provides ai.gateway
    And its durable database is recoverable through a logical PostgreSQL dump
