# OpenSpec traceability

The table is deliberately small. The Gherkin tag is the stable contract identifier; tests and runtime evidence may evolve without renaming the behaviour.

| Contract | Primary automated evidence | Additional evidence |
|---|---|---|
| `PLATFORM-DEP-001` | `tests/test_openspec_contracts.py::test_PLATFORM_DEP_001_required_dependencies_are_declared` | manifest planner tests |
| `PLATFORM-RUNTIME-001` | installer/manifest tests | repository runtime/source contract |
| `INSTALL-PLAN-001` | `tests/test_installer.py` | installer plan output |
| `INSTALL-LIFECYCLE-001` | `tests/test_openspec_contracts.py::test_INSTALL_LIFECYCLE_001_restart_reconcile_waits_ready` | `tests/test_stack6_reconcile_ready.py` |
| `INSTALL-LOCK-001` | `tests/test_installer.py` | stack PREPARE contracts |
| `DR-BACKUP-001` | `tests/test_openspec_contracts.py::test_DR_BACKUP_001_stack7_artifact_is_declared` | `tests/disaster_recovery/test_dr_backup_all.py` |
| `DR-RESTORE-001` | `tests/disaster_recovery/test_dr_restore_all.py` | qualified clean-target recovery |
| `DR-STACK7-001` | `tests/test_openspec_contracts.py::test_DR_STACK7_001_restore_contract_preserves_data_and_identity` | `docs/dr/status.md` isolated restore qualification |
| `STACK0-FOUNDATION-001` | recovery/manifest tests | Stack0 verify script |
| `STACK1-INGRESS-001` | stack/installer contracts | deployed HAProxy qualification |
| `STACK2-WEB-001` | `tests/test_stack7_web_capabilities.py` | regular-user web qualification |
| `STACK3-GATEWAY-001` | DR and recovery-contract tests | deployed LiteLLM qualification |
| `STACK4-GIT-001` | `tests/disaster_recovery/test_dr_stack4_restore_verify.py` | Gitea backup/restore qualification |
| `STACK5-RECONSTRUCT-001` | recovery-contract tests | manifest declares reconstructable state |
| `STACK6-ISOLATION-001` | `tests/test_openspec_contracts.py::test_STACK6_ISOLATION_001_hermes_has_no_docker_socket` | SDR-0002 |
| `STACK6-MEMORY-001` | `tests/disaster_recovery/test_dr_stack6_verify.py` | host Git-memory qualification |
| `STACK7-POLICY-001` | `tests/test_openspec_contracts.py::test_STACK7_POLICY_001_access_is_explicit_not_bypassed` | regular-user qualification |
| `STACK7-WEB-001` | `tests/test_openspec_contracts.py::test_STACK7_WEB_001_web_search_is_default_interface_behaviour` | real `search_web` / `fetch_url` qualification |
| `CLI-BOUNDARY-001` | `tests/test_management_cli.py::test_cli_boundary_exposes_versioned_json_upgrade_contract` | ADR-0002 |
| `CLI-UPGRADE-001` | `tests/test_management_cli.py::test_upgrade_check_contains_all_declared_components_and_selected_column` | `internal/upgrade-components.json` |
| `CLI-UPGRADE-002` | `tests/test_management_cli.py::test_stack7_shorthand_select_persists_plan_without_runtime_change` | installation-local `upgrade-plan.json` |
| `CLI-UPGRADE-003` | `tests/test_management_cli.py::test_upgrade_yes_never_auto_selects_available_versions` | ADR-0002 |
| `CLI-UPGRADE-004` | `tests/test_management_cli.py::test_stale_plan_fails_before_execution` | structured `UPGRADE_PLAN_STALE` error |
| `CLI-UPGRADE-005` | `tests/test_upgrade_executor.py` | targeted deploy metadata in `internal/upgrade-components.json` and recovery-first executor |
