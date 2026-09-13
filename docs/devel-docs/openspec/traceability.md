# OpenSpec traceability

Every tagged behavioral contract must have executable or qualified evidence. The Gherkin tag is the stable behavior identifier; implementation files and individual test functions may evolve as long as equivalent evidence remains. Runtime qualification complements automated evidence when the behavior depends on real Docker/registry/application interaction.

| Contract | Primary automated evidence | Additional evidence |
|---|---|---|
| `PLATFORM-DEP-001` | `tests/test_openspec_contracts.py::test_PLATFORM_DEP_001_required_dependencies_are_declared` | manifest planner tests |
| `PLATFORM-RUNTIME-001` | installer/manifest and repository-layout tests | `/opt/docker/stacks` vs `/opt/docker/runtime` ownership contract |
| `INSTALL-PLAN-001` | `tests/test_installer.py`, `tests/test_management_cli.py` install passthrough | `./local-ai install --plan ...` qualification |
| `INSTALL-LIFECYCLE-001` | `tests/test_openspec_contracts.py::test_INSTALL_LIFECYCLE_001_restart_reconcile_waits_ready` | `tests/test_stack6_reconcile_ready.py`, including direct-script executable checks, plus m92p installer/runtime gates |
| `INSTALL-LOCK-001` | `tests/test_installer.py` | stack PREPARE contracts |
| `DR-BACKUP-001` | `tests/test_openspec_contracts.py::test_DR_BACKUP_001_stack7_artifact_is_declared` | `tests/disaster_recovery/test_dr_backup_all.py` and qualified global backup |
| `DR-RESTORE-001` | `tests/disaster_recovery/test_dr_restore_all.py`, restore-live/compat tests | qualified clean-target recovery and historical installer compatibility |
| `DR-STACK7-001` | `tests/test_openspec_contracts.py::test_DR_STACK7_001_restore_contract_preserves_data_and_identity` | [`docs/dr/status.md`](../../dr/status.md) isolated restore qualification |
| `STACK0-FOUNDATION-001` | recovery/manifest tests | Stack0 verify script |
| `STACK1-INGRESS-001` | stack/install contracts | deployed HAProxy qualification |
| `STACK2-WEB-001` | `tests/test_stack7_web_capabilities.py` | real Stack2-backed web search/extraction qualification |
| `STACK3-GATEWAY-001` | DR and recovery-contract tests | deployed LiteLLM qualification and SDR-0003 |
| `STACK4-GIT-001` | `tests/disaster_recovery/test_dr_stack4_restore_verify.py` | Gitea native backup/restore qualification |
| `STACK5-RECONSTRUCT-001` | recovery-contract tests | manifest reconstructable-state contract |
| `STACK6-ISOLATION-001` | `tests/test_openspec_contracts.py::test_STACK6_ISOLATION_001_hermes_has_no_docker_socket` | [`SDR-0002`](../sdr/0002-agent-runtime-without-docker-socket.md) |
| `STACK6-MEMORY-001` | `tests/disaster_recovery/test_dr_stack6_verify.py` | host Git-memory and DR qualification |
| `STACK7-POLICY-001` | `tests/test_openspec_contracts.py::test_STACK7_POLICY_001_access_is_explicit_not_bypassed` | regular-user qualification and SDR-0005 |
| `STACK7-WEB-001` | `tests/test_openspec_contracts.py::test_STACK7_WEB_001_web_search_is_default_interface_behaviour` | real `search_web` / `fetch_url` qualification |
| `CLI-BOUNDARY-001` | `tests/test_management_cli.py::test_cli_boundary_exposes_versioned_json_upgrade_contract` | [`ADR-0002`](../adr/0002-single-management-cli.md) and root-boundary m92p gate |
| `CLI-LAYOUT-001` | `tests/test_repository_layout.py::test_local_ai_is_the_supported_root_management_cli` | [`ADR-0005`](../adr/0005-unified-command-implementation-package.md) |
| `CLI-UPGRADE-001` | `tests/test_management_cli.py::test_upgrade_check_contains_all_declared_components_and_selected_column` | `commands/upgrade-components.json`, registry discovery qualification |
| `CLI-UPGRADE-002` | `tests/test_upgrade_selection_policy.py` | installation-local `upgrade-plan.json` including immutable target digest |
| `CLI-UPGRADE-003` | `tests/test_management_cli.py::test_upgrade_yes_never_auto_selects_available_versions` | ADR-0002 |
| `CLI-UPGRADE-004` | `tests/test_management_cli.py::test_stale_plan_fails_before_execution` | structured `UPGRADE_PLAN_STALE` error |
| `CLI-UPGRADE-005` | `tests/test_upgrade_executor.py` | targeted deploy metadata, recovery-first executor and successful Hermes live upgrade |
| `CLI-UPGRADE-006` | `tests/test_upgrade_executor.py`, `tests/test_upgrade_selection_policy.py` | registry digest captured at selection and tag-movement rejection before recovery or `.env` mutation |
| `CLI-POLICY-001` | `tests/test_upgrade_policy.py::test_override_is_installation_local_and_clear_restores_default` | catalog defaults and installation-local policy file |
| `CLI-POLICY-002` | `tests/test_upgrade_policy.py::test_minor_series_accepts_only_newer_same_major_minor` | [`ADR-0004`](../adr/0004-upgrade-compatibility-policy.md) |
| `CLI-POLICY-003` | `tests/test_upgrade_policy.py::test_major_series_accepts_newer_same_major` | ADR-0004 and Hermes date-like version qualification |
| `CLI-POLICY-004` | `tests/test_upgrade_policy.py::test_manual_uses_explicit_target_without_series_inference` | exact registry-target validation in `commands/upgrade_entry.py` |
| `CLI-POLICY-005` | `tests/test_upgrade_policy.py::test_override_is_installation_local_and_clear_restores_default` | `./local-ai upgrade policy ... clear` runtime gate |
| `CLI-POLICY-006` | `tests/test_upgrade_policy.py::test_policy_change_marks_existing_selection_invalid_without_clearing_it` | `UPGRADE_TARGET_UNSUPPORTED` revalidation |
| `CLI-POLICY-007` | `tests/test_management_cli.py::test_nonselectable_component_is_rejected` | catalog `selectable` flag remains independent |
| `CLI-POLICY-008` | `tests/test_upgrade_executor.py::test_executor_revalidates_policy_before_target_preflight_or_mutation` | executor policy preflight |
| `CLI-STATUS-001` | `tests/test_status.py::test_inventory_keeps_desired_deployed_and_actual_separate` | `./local-ai status` runtime inventory qualification |
| `CLI-STATUS-002` | `tests/test_status.py::test_drift_is_quick_yes_no_or_na_decision` | versioned `./local-ai --json status` contract |
| `CLI-STATUS-003` | `tests/test_status.py::test_inventory_resolves_floating_tag_to_registry_identities`, `test_floating_tag_same_digest_is_proven_no_drift`, `test_fixed_semantic_tag_does_not_require_registry_resolution_for_drift`, `test_digest_pins_compare_immutable_identity_without_registry_resolution`, `test_status_and_upgrade_check_share_concrete_actual_for_floating_tag`, `test_floating_tag_registry_failure_never_claims_no_drift` | m92p runtime evidence: HAProxy moved `3.0.26 -> 3.0.27`, Redis moved `8.10.0 -> 8.10.1`, RabbitMQ unchanged `3.13.7`; registry-backed status now exposes the real drift rather than tag-text equality |

## Traceability maintenance

A new tagged scenario must be added to this table in the same change and must name real evidence. A test rename may update the evidence reference without renaming the behavioral tag. A removed behavior must state whether it was superseded or retired; silently deleting the traceability row is not sufficient.
