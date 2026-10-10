<!-- This Source Code Form is subject to the terms of the Mozilla Public
     License, v. 2.0. If a copy of the MPL was not distributed with this
     file, You can obtain one at https://mozilla.org/MPL/2.0/. -->

# Stack 80 · Self-hosted MCP servers

This Compose file runs independent MCP servers. Docker services, containers,
and manual client registrations use `mcp-XXX` names. The stack does not
configure, modify, or register anything in LiteLLM. Integration with `local-ai`
is pending; current operations use Docker Compose directly.

| Service | Endpoint on `redlocal` | Features |
| --- | --- | --- |
| `mcp-gdrive` | `http://mcp-gdrive:8000/mcp` | Search, list, upload, download, create folders, copy, move, update files, and manage permissions |
| `mcp-gmail` | `http://mcp-gmail:8000/mcp` | Search and read messages, threads, and attachments; compose drafts and send email on demand |
| `mcp-gcalendar` | `http://mcp-gcalendar:8000/mcp` | All upstream calendar tools: calendars, events, invitation responses, availability, out-of-office events, and focus time |

All three use [google_workspace_mcp v2.1.0](https://github.com/taylorwilsdon/google_workspace_mcp/tree/v2.1.0),
with source selected by version number and dependencies from the upstream
`uv.lock`. The operator controls upgrades by changing
`GOOGLE_WORKSPACE_MCP_VERSION` in the global `.env` (without the `v` prefix).
Compose uses that number for both the local image tag and the source release
tag, `v<VERSION>`.

The upstream project uses the MIT license; this stack's own files include
MPL-2.0 headers. The image is built locally from the upstream Dockerfile.
The stack does not use Google's managed `drivemcp`/`gmailmcp` endpoints or
domain-wide delegation. The upstream project states that it supports free
`@gmail.com` accounts.

## Layout

```text
stack-80_-_mcp/
├── .env -> ../.env                  # central environment, not a local copy
├── __init__.py
├── 00-bootstrap.py                  # optional settings preparation
├── 01-prepare.py                    # settings, validation, and directories
├── authorize.py                     # manual Google consent or credential check
├── google-oauth.py                  # helper executed inside each MCP
├── docker-compose.yml
├── stack_env.py                     # shared MCP selection
├── wait-ready.py
└── config/
    ├── mcp-gdrive/.env.example
    ├── mcp-gmail/.env.example
    └── mcp-gcalendar/.env.example
```

Tests are in `tests/stack_80/` at the repository root. `BASE_PATH` and
`NETWORK_NAME` are reused from the global `.env`. Section 80 of the global
`.env.template` documents `GOOGLE_WORKSPACE_MCP_VERSION`,
`MCP_GOOGLE_OAUTH_CLIENT_ID`, `MCP_GOOGLE_OAUTH_CLIENT_SECRET`,
`MCP_GOOGLE_EMAIL`, `MCP_UID`, and `MCP_GID`. Preparation creates the
stack's symlink without modifying the global file.

Scripts operate on all services by default; `--mcp mcp-gmail` selects one.
Compose also supports selecting a service by name. Data is stored in
`${BASE_PATH}/service_-_mcp-gdrive/data/`,
`${BASE_PATH}/service_-_mcp-gmail/data/`, and
`${BASE_PATH}/service_-_mcp-gcalendar/data/`, with `credentials/` and
`attachments/` subdirectories. Persistent credentials are not shared between
instances. All three instances can currently use the same account and Client ID.

## Authentication model

Google authentication belongs to the containers, not LiteLLM. The stack uses
`MCP_ENABLE_OAUTH21=false`, `EXTERNAL_OAUTH21_PROVIDER=false`, and
`MCP_SINGLE_USER_MODE=1`. Each instance loads the dedicated account's credentials
from `/data/credentials`, refreshes expired access tokens when needed, and saves
updated credentials, including rotated refresh tokens, to the same persistent
store. `USER_GOOGLE_EMAIL` supplies the account default for tool calls.

Declare the following **once in the central `.env`**:

- `MCP_GOOGLE_OAUTH_CLIENT_ID`: the Google OAuth **Desktop App** Client ID.
- `MCP_GOOGLE_OAUTH_CLIENT_SECRET`: the matching Desktop App secret.
- `MCP_GOOGLE_EMAIL`: the dedicated Google account's email.

Compose passes these settings to all three instances. Per-MCP `.env` files
are reserved for service-specific settings, not repeated Google configuration.
Preparation removes obsolete internal OAuth signing keys from per-MCP settings.

There is no OAuth challenge on the internal `/mcp` endpoints. LiteLLM controls
agent access with its virtual keys and MCP grants. Any other container with
access to `redlocal` can also reach these endpoints, so access to that network
must be controlled. No host ports are published. The container bootstrap helper
is mounted read-only and runs only when the operator invokes it; it is not an
MCP tool. `start_google_auth` is disabled in all three services.

References: upstream [single-user lookup and refresh](https://github.com/taylorwilsdon/google_workspace_mcp/blob/v2.1.0/auth/google_auth.py)
and [HTTP authentication configuration](https://github.com/taylorwilsdon/google_workspace_mcp/blob/v2.1.0/core/server.py).

## Preparation and startup

Prepare the central `.env` using the platform's procedure and section 80 of
`.env.template`. Use the Desktop App credentials, replacing the Web App Client
ID previously used for LiteLLM's OAuth flow. Do not repeat `BASE_PATH` or
`NETWORK_NAME`. Run the commands on the **Docker host**, from the stack directory:

```bash
python3 01-prepare.py
python3 01-prepare.py --validate-only
docker compose --env-file .env build
docker compose --env-file .env up -d
python3 wait-ready.py
```

The stack's `.env` is a symlink to `../.env`; preparation does not modify the
global environment. An existing independent stack `.env` is rejected rather
than overwritten. `--validate-only` does not write files. `00-bootstrap.py`
optionally prepares settings without Docker validation or runtime directories.
Preparation preserves service-specific settings and removes obsolete OAuth
signing keys and local copies of Google Client ID, Client Secret, and email;
the central Google values are authoritative.
Per-MCP settings have `0600` permissions and runtime directories have `0700`.
Preparation changes ownership only for newly created directories.

An existing bridge `redlocal` network is required. Google must be reachable
over HTTPS from the containers. Set `MCP_UID`/`MCP_GID` to the intended container
user and run preparation as root or that user. Readiness does not imply Google
has been authorized yet.

### Migrating the previous external OAuth deployment

Complete the three Google settings in the central `.env`, then run:

```bash
python3 01-prepare.py
docker compose --env-file .env up -d --force-recreate
python3 wait-ready.py
python3 authorize.py
python3 authorize.py --check
```

The image release remains `2.1.0`; the migration changes runtime configuration
and mounts the new helper. Existing data directories are retained. Tokens held
by LiteLLM are not copied or reused. The operator completes a new Google consent
flow for each instance. Neither preparation nor startup starts that flow.

## Manual Google authorization

Use the existing **Desktop OAuth App**, not a service account or domain-wide
delegation. Enable Drive API, Gmail API, and Google Calendar API in its Google
Cloud project. This does not require the Workspace Developer Preview Program.
For a personal account, configure the OAuth audience as **External**. If the
app is in Testing, add the account as a test user; refresh tokens for these
scopes can expire after seven days and require renewed authorization.

Authorize one MCP, or omit `--mcp` to authorize all three in sequence:

```bash
python3 authorize.py --mcp mcp-gmail
```

1. The helper runs inside the selected container and prints a Google consent URL.
2. Open that URL on your client user device and choose the configured agent account.
3. Google redirects to `http://localhost:8765/`. No listener is started, so the
   browser will report that the page cannot load. Copy the **complete resulting
   URL from the address bar** and paste it into the terminal's hidden prompt.
4. The helper validates the callback address and OAuth state, exchanges the code
   using PKCE, checks the account identity and granted scopes, and stores the
   access/refresh credentials in that MCP's persistent directory.

This uses the Desktop App's loopback redirect, not the deprecated Google OOB
redirect. No MCP callback needs to be reachable from the browser, and no tunnel,
host port, or LiteLLM callback is required. Do not share the callback URL: it
contains a temporary authorization code. Tokens and client secrets are not
printed by the helper or included in host command arguments.

Requested scopes are limited to the enabled operations, plus `openid` and
`userinfo.email` for identity verification:

| MCP | Google API scopes |
| --- | --- |
| `mcp-gdrive` | `https://www.googleapis.com/auth/drive` |
| `mcp-gmail` | `https://www.googleapis.com/auth/gmail.readonly`, `https://www.googleapis.com/auth/gmail.compose`, `https://www.googleapis.com/auth/gmail.send` |
| `mcp-gcalendar` | `https://www.googleapis.com/auth/calendar` |

Check stored credentials without starting another consent flow:

```bash
python3 authorize.py --check
```

This uses upstream's credential lookup and refresh implementation. Expired
access tokens are refreshed and saved. A successful check confirms a stored
refresh token and valid access token; it does not prove every Google API
operation succeeds. A revoked/expired refresh token, changed OAuth app, or
missing permissions requires running authorization again for the affected MCP.

References: [Google Desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app),
[consent configuration](https://developers.google.com/workspace/guides/configure-oauth-consent),
[token expiration](https://developers.google.com/identity/protocols/oauth2#expiration).

## Manual registration in LiteLLM

The user performs these actions; the stack does not edit LiteLLM configuration
or change virtual keys, users, roles, or existing registrations.

| Field | Value |
| --- | --- |
| Name / Alias | `mcp-gdrive`, `mcp-gmail`, or `mcp-gcalendar` |
| Transport | Streamable HTTP |
| MCP Server URL | Internal endpoint from the first table |
| Authentication | None (no upstream OAuth) |

For existing records, replace OAuth authentication with None and remove their
Google OAuth configuration. Keep the virtual keys' existing MCP grants and
route restrictions. Agents continue to authenticate to **LiteLLM** with their
virtual keys; they do not need Google tokens or a LiteLLM user identity to use
these three upstream servers.

## Verification and limitations

`/health/ready` confirms process readiness, **not** Google authorization.
MCP initialization and tool discovery work without an upstream OAuth token,
including before Google consent. Verify actual Google access separately with
`authorize.py --check` and read operations in each service. Then use authorized
test data for write operations and email sending. Calls happen on demand;
there is no background polling of Gmail or Calendar.

Drive does not enable Docs, Sheets, or Slides editing tools or their importers;
it can manage those files and export them where supported by Drive API.
The upstream server supports moving files to the trash through
`update_drive_file(trashed=true)`; this version does not provide a tool for
permanently deleting files. Gmail does not add polling, push notifications,
filter management, or label modification. Attachments and Drive downloads
remain in each service's own directory. Internal download URLs are accessible
from `redlocal`, not directly from the user's browser.

Calendar enables all seven upstream tools without additional filters:
`list_calendars`, `get_events`, `manage_event`, `create_calendar`,
`query_freebusy`, `manage_out_of_office`, and `manage_focus_time`.
`manage_event` supports creating, modifying, and deleting events and responding
to invitations. This covers all operations exposed by this MCP, not the entire
Google API. Google restricts special out-of-office and focus-time events to
eligible accounts; enabling the tools does not remove those restrictions.
Reference: [Calendar status events](https://developers.google.com/workspace/calendar/api/guides/calendar-status).

This deployment uses one dedicated account. The bootstrap rejects consent
from a different account; it does not implement isolation between multiple
agent identities sharing that account. Credentials are private JSON files
inside the persistent data directories and must be protected with the host
permissions and backups. Changing the Client ID or secret requires renewed
authorization; saved files include the OAuth app information used for refresh.

The new container-managed flow still needs real Google authorization and an
integration check on the deployment host. Local isolated checks are described
in `VERIFICATION.md`.
