<!-- This Source Code Form is subject to the terms of the Mozilla Public
     License, v. 2.0. If a copy of the MPL was not distributed with this
     file, You can obtain one at https://mozilla.org/MPL/2.0/. -->

# Verification · Stack 80

## Management integration · October 13, 2026

The repository now provides `local-ai stack-80 install/start/stop/status/reconfig`.
Local automated checks cover the platform directory map, adoption of compatible
running containers, preparation locks, private backups, refusal of unsafe paths
and permission drift, and read-only reconfiguration previews. Tests also check
that lifecycle commands neither authorize Google nor modify LiteLLM. The deep
status client initializes an MCP session and lists tools; its client sequence is
tested with fixture transports, without calling Google tools or refreshing tokens.

The operator previously confirmed that all three deployed MCPs work and appear
healthy in LiteLLM. That deployment confirmation is separate from automated
fixture tests. The new management integration has not yet been exercised on
m92p; adoption and `status --deep` remain manual deployment checks.

## Authentication verification · October 10, 2026

These checks validate the new container-managed Google authentication flow.
No real Google credentials or LiteLLM configuration were used or changed.

## Completed checks

- Docker Compose renders and validates all three services with fixture values,
  with version `2.1.0`, no published ports, and only the existing `redlocal`
  network. Credential stores remain separate persistent bind mounts.
- Client ID, matching secret, and account email are declared only in the central
  environment. Per-service files contain no repeated Google settings.
- Bootstrap and preparation preserve the central file, create the canonical
  symlink, preserve service-specific settings, remove obsolete OAuth signing
  keys and local Google copies, and remain idempotent. Existing independent
  stack environment files are rejected without being overwritten.
- Preparation creates private runtime directories using mocked Docker checks.
  Per-service environment files have `0600` permissions.
- Callback tests reject wrong destinations, wrong/missing/duplicate state,
  duplicate codes, declined consent, and fragments before code exchange.
- Stack scripts disable Python bytecode before local imports. Preparation
  preserves Python source content and modes; bootstrap does not create
  `__pycache__` artifacts. The project's bytecode, shebang, and Compose
  healthcheck tests pass, alongside the focused stack tests.
- Isolated tests run the actual upstream `v2.1.0` server and dependencies in a
  temporary environment, using the Compose arguments with local test addresses.
- The actual Google OAuth library builds an offline consent URL with PKCE
  (`S256`), exchanges a fixture authorization code, and stores a verified
  account's credentials with private permissions. Only Google's HTTPS token
  transport and userinfo response are mocked; no real Google request is made.
  Wrong-account consent and grants without a refresh token are rejected
  without replacing previously stored credentials.
- Upstream's real credential lookup and google-auth refresh implementation
  refresh an expired fixture access token. The rotated refresh token and access
  token are saved and read back from disk. A lookup for a different account does
  not fall back to the stored account.
- Each server returns 200 from `/health/ready`. An MCP client without an OAuth
  header initializes and lists 13 Drive tools, 8 Gmail tools, and 7 Calendar
  tools. The Google email is not required in tool arguments, and
  `start_google_auth` is absent from all three tool lists.
- The focused pytest suite passes. Tests live only in `tests/stack_80/` at the
  repository root. Stack scripts, tests, and documentation retain MPL headers.

No Google API read/write operations, email sending, or remote deployment were
performed. The refresh and initial authorization results use simulated Google
responses; they do not prove a real account grant succeeds.

## Repeating the checks

From the repository root, run the focused tests and Compose checks (Docker
Compose CLI required, without a running Docker daemon):

```bash
python3 -B -m pytest -q -p no:cacheprovider tests/stack_80
python3 -B tests/stack_80/verify.py
```

For isolated upstream HTTP, authorization, and refresh checks, use a temporary
checkout and its dependency environment outside the repository:

```bash
git clone --depth 1 --branch v2.1.0 \
  https://github.com/taylorwilsdon/google_workspace_mcp.git /tmp/workspace-mcp-check
git -C /tmp/workspace-mcp-check describe --tags --exact-match
# Expected: v2.1.0.
uv sync --project /tmp/workspace-mcp-check --frozen --no-dev --extra disk
/tmp/workspace-mcp-check/.venv/bin/python -B tests/stack_80/verify.py \
  --upstream /tmp/workspace-mcp-check
```

## Deployment verification

The operator has confirmed successful deployment and container-managed Google
authorization on m92p. Do not repeat the earlier OAuth migration solely to adopt
the deployment into `local-ai`. Follow the README's adoption procedure first,
then check `./local-ai stack-80 status --deep`. When explicitly recreating a
container, repeat `python3 authorize.py --check` to verify persisted credentials;
that command can refresh and save tokens.

LiteLLM registration and Google access remain operator-managed. The management
integration does not change registrations, users, virtual keys, or Google grants.
Real searches, calendar reads, authorized test writes, email sending, and real
token refresh are separate checks from MCP readiness. Google account restrictions
and revoked/expired refresh tokens still apply.
