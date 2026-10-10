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
├── 01-prepare.py                    # settings, keys, validation, and directories
├── docker-compose.yml
├── reconfig.py                      # reserved for local-ai
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
`MCP_GOOGLE_OAUTH_CLIENT_ID`, `MCP_UID`, and `MCP_GID`. Preparation creates the
stack's symlink without modifying the global file.

Scripts operate on all services by default; `--mcp mcp-gmail` selects one.
Compose also supports selecting a service by name. Data is stored in
`${BASE_PATH}/service_-_mcp-gdrive/data/`,
`${BASE_PATH}/service_-_mcp-gmail/data/`, and
`${BASE_PATH}/service_-_mcp-gcalendar/data/`, with `credentials/` and
`attachments/` subdirectories. Persistent credentials are not shared between
instances. All three instances can currently use the same account and Client ID.

## Authentication model

The stack uses `MCP_ENABLE_OAUTH21=true` and `EXTERNAL_OAUTH21_PROVIDER=true`.
The external client obtains a Google access token and sends it as
`Authorization: Bearer <access_token>`. The MCP validates the identity with
Google and uses that token for Drive, Gmail, or Calendar requests. The client
is responsible for token refresh; the MCP does not exchange authorization
codes or retain refresh tokens from the external flow.

The upstream server requires a **local Client ID** even in this mode. It is
not secret: set `MCP_GOOGLE_OAUTH_CLIENT_ID` once in the global `.env`.
Compose passes it to all three instances as `GOOGLE_OAUTH_CLIENT_ID`.
The `config/mcp-XXX/.env` files contain no Client ID copies, only the internal
signing keys that `01-prepare.py` generates for each instance and preserves
on subsequent runs. These keys are separate from the Google Client Secret.

**The Google Client Secret is entered only in the external client**.
Compose forces `GOOGLE_OAUTH_CLIENT_SECRET` to an empty value. Scopes are
requested by the client; available tools are restricted in each container.

Reference: [external provider](https://github.com/taylorwilsdon/google_workspace_mcp/blob/v2.1.0/auth/external_oauth_provider.py).

## Preparation and startup

First prepare the central `.env` using the platform's procedure and add the
variables from section 80 of `.env.template`. There is no need to repeat
`BASE_PATH` or `NETWORK_NAME`. Run the commands below on the **Docker host**,
from the stack directory, with permission to read the central environment.

Set `MCP_GOOGLE_OAUTH_CLIENT_ID` once in the global `.env` using the Web App's
Client ID. Do not edit per-MCP files manually. `01-prepare.py` creates the
symlink and any missing keys before validating Compose and preparing data
directories. `00-bootstrap.py` is optional: it only prepares settings, without
validating Docker or creating data directories.

The stack's `.env` is an exact symlink to `../.env`; an independent environment
file is not generated. If an old local `.env` exists, preparation stops so the
operator can preserve its values in the central file before removing it.
Set `MCP_UID`/`MCP_GID` in the global environment for the container user.
When run as root, preparation assigns ownership only to new directories;
it does not change ownership of existing directories. Generated per-MCP
settings are excluded from Git, and internal keys are not printed. Obsolete
local Client ID copies are removed during preparation; the global value is
the only authority.

```bash
python3 01-prepare.py
python3 01-prepare.py --validate-only
docker compose --env-file .env build
docker compose --env-file .env up -d
python3 wait-ready.py
```

`--validate-only` does not write files; use it after initial preparation.

Preparation requires an existing bridge network and does not create it.
There are no published `ports:`; clients must share `redlocal`. Google must
be reachable over HTTPS from the containers; `redlocal` does not imply a
network without Internet access.

To recreate only one instance after changing its configuration:

```bash
docker compose --env-file .env up -d --no-deps --force-recreate mcp-gmail
python3 wait-ready.py --mcp mcp-gmail
```

## Manual registration in LiteLLM

This section is a user guide; the stack does not perform these actions.
Under **MCP Servers → Add New MCP Server**, configure each instance separately:

| Field | Value |
| --- | --- |
| Name / Alias | `mcp-gdrive`, `mcp-gmail`, or `mcp-gcalendar` |
| Transport | Streamable HTTP |
| MCP Server URL | Internal endpoint from the first table |
| Authentication | OAuth |
| OAuth Flow Type | Interactive (PKCE) |
| Client ID | Your Google OAuth **Web App** ID, matching `MCP_GOOGLE_OAUTH_CLIENT_ID` in the global environment |
| Client Secret | The Web App's secret, entered by the user in LiteLLM |
| Issuer | `https://accounts.google.com` |
| Authorization URL | `https://accounts.google.com/o/oauth2/v2/auth` |
| Token URL | `https://oauth2.googleapis.com/token` |
| Token Header | `Authorization` |
| Token Endpoint Auth Method | Client Secret Post |
| Registration URL | Leave empty; the existing static client is used |

Request these scopes:

- All three: `openid`, `https://www.googleapis.com/auth/userinfo.email`, and
  `https://www.googleapis.com/auth/userinfo.profile` (user identification).
- Drive: `https://www.googleapis.com/auth/drive` (full file management).
- Gmail: `https://www.googleapis.com/auth/gmail.readonly`,
  `https://www.googleapis.com/auth/gmail.send`, and
  `https://www.googleapis.com/auth/gmail.compose` (drafts).
- Calendar: `https://www.googleapis.com/auth/calendar` (full management).

The Web App must have **LiteLLM's** callback URI registered, rather than the
MCP container's callback. LiteLLM's documentation specifies
`<LiteLLM origin>/callback`; check the actual flow's `redirect_uri` before
entering it in Google Cloud. The browser returns to LiteLLM and does not
need to resolve the MCP containers' internal names.

Enable Drive API, Gmail API, and Google Calendar API
(`calendar-json.googleapis.com`) in the credentials' project. For a personal
account, use the **External** OAuth audience rather than **Internal**.
If the app is in Testing, add the account as a test user and account for
the seven-day refresh token expiration for these scopes.

References: [LiteLLM OAuth](https://docs.litellm.ai/docs/mcp_oauth),
[Google consent configuration](https://developers.google.com/workspace/guides/configure-oauth-consent),
[token expiration](https://developers.google.com/identity/protocols/oauth2#expiration).

## Verification and limitations

`/health/ready` confirms process readiness, **not** Google authorization.
A request to `/mcp` without a token should return 401. After completing OAuth
manually, verify in LiteLLM that each service lists its tools and that file
search, message search, and calendar/event listing work. Then check token
refresh and, using authorized test data, write operations and email sending.

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

External mode identifies the user from the token, but this deployment is
designed for one agent account. It does not include account restrictions
or a design for isolation between multiple users.

Real Google authorization and a complete integration test through LiteLLM
have not been performed. Compose validation and isolated tests are described
in `VERIFICATION.md`.
