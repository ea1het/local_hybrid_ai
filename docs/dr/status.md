# DR qualification status

This file records evidence, not design intent. Read it with [howto.md](howto.md), [../../bkp-dr/README.md](../../bkp-dr/README.md), [../a2aknowledge.md](../a2aknowledge.md), [../pending.md](../pending.md), [../../adr/](../../adr/) and [../../sdr/](../../sdr/).

## Core clean-target recovery — PASS

A real destructive recovery of the reference host was authorized and completed before Stack7 was introduced.

```text
backup set: /opt/local-hybrid-ai-backups/backup-20260911T172551Z
source commit: 7cbfa2874f6e865a4de6e2854b2589de52a39913
resolved stacks: 0,1,2,3,4,5,6
LiteLLM PostgreSQL tables: 75
Gitea SQLite tables: 116
Gitea repositories: 8
portable memory HEAD: e9c220aa26b29303a18fa4b3f43f1c6edc0760ca
hermes-memory-sync: running
```

The recovery point checksum index remained valid and restored source matched the recorded commit. A bounded resume was used after recovery-tooling defects were discovered; the host was not wiped again and managed state was not blindly re-imported.

## Stack7 global recovery point — PASS

```text
backup set: /opt/local-hybrid-ai-backups/backup-20260912T213405Z
source commit: c087f83c3a36304921a67d7cd888696d176868ab
resolved stacks: 0,1,2,3,4,5,6,7
artifacts: 5
prerequisites: 3
published atomically: true
```

The complete checksum index passed, including `artifacts/stack7/open-webui-data.tar` (933,140,480 bytes).

The Stack7 archive was restored into an isolated temporary runtime using the DR engine's safe archive extractor:

```text
archive members restored: 119
webui.db exists: true
users: 2
admins: 1
regular users: 1
chats: 2
active basic_autorouter rows: 1
public read grants: 1
ui.default_models: "basic_autorouter"
evaluation.arena.enable: false
ui.default_interface_settings: {"webSearch":"always"}
temporary cleanup: PASS
live runtime modified: no
live open-webui: running/healthy
```

An earlier ad-hoc `tarfile.extractall(filter="data")` check rejected a Hugging Face cache symlink. That was a verifier mismatch, not backup corruption; the actual DR extractor restored the archive successfully.

## Stack7 functional qualification — PASS

A clean Stack7 deployment proved `basic_autorouter` selected by default, Arena disabled, explicit public-read model policy, regular-user access limited to the curated model, Web Search enabled by default, and real `search_web`/`fetch_url` results. SearXNG/Firecrawl per-request correlation is not observable in current container logs; that is an observability limitation, not claimed provider-log evidence.

## Preserve as evidence

Verified backup sets under `/opt/local-hybrid-ai-backups` are recovery evidence, not generic cleanup. Do not repeat the destructive wipe or Stack7 isolated restore only to reproduce an already-qualified result.
