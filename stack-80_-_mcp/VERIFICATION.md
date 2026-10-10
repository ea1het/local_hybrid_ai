<!-- This Source Code Form is subject to the terms of the Mozilla Public
     License, v. 2.0. If a copy of the MPL was not distributed with this
     file, You can obtain one at https://mozilla.org/MPL/2.0/. -->

# Verification · October 10, 2026

The stack was verified without modifying or registering services in LiteLLM
and without using real Google credentials.

## Completed checks

- Docker Compose v5.3.1 renders and validates the file with test settings.
- Bootstrap selects one MCP or all of them, preserves existing values on
  subsequent runs, and generates separate keys with `0600` permissions.
- The stack environment is a symlink to `../.env`; bootstrap and validation
  leave the global file unchanged. Bootstrap rejects an old local `.env`
  without overwriting it and does not create a missing global environment.
- `01-prepare.py` generates internal settings and keys without requiring
  bootstrap first. The Client ID is declared once in the global environment,
  and Compose passes it to all three instances. Obsolete local copies are
  removed while signing keys are preserved. This preparation is tested with
  mocked Docker operations.
- All three services use only the external network, publish no ports, have
  separate directories, and force the Google Client Secret to an empty value.
- The build references the `v2.1.0` release tag of `google_workspace_mcp`;
  `GOOGLE_WORKSPACE_MCP_VERSION` lets the operator change the version.
- The upstream project was installed in a temporary Python 3.11 environment
  using its `uv.lock` (`uv sync --frozen --no-dev --extra disk`), without
  changing its source.
- Each HTTP server was started with the Compose arguments and environment,
  replacing storage paths and addresses with temporary values.
- `/health/ready` returns 200, and `/mcp` returns 401 for missing or rejected
  tokens. The MCP client performs `initialize` and `tools/list` with a test
  token: 13 Drive tools, 8 Gmail tools, and 7 Calendar tools, without mixing
  service tool sets.
- The real external provider converts the bearer token into credentials
  containing the same token, without a Google Client Secret or refresh token.
- Python syntax, MPL headers, and the scope of changes were checked:
  `stack-80_-_mcp/`, its tests in `tests/stack_80/`, and the stack 80 section
  of the global `.env.template`.

The HTTP tests mock only Google's `userinfo` response. The test token is not
a real authorization. No Drive, Gmail, or Calendar API calls, email sending,
write operations, or deletions were performed.

## Repeating the checks

From the repository root, check the Compose and bootstrap contracts with
Docker Compose installed (no Docker daemon required):

```bash
python3 -B tests/stack_80/verify.py
python3 -B -m pytest -q -p no:cacheprovider tests/stack_80
```

For the additional upstream test, use a temporary directory outside the
repository:

```bash
git clone --depth 1 --branch v2.1.0 \
  https://github.com/taylorwilsdon/google_workspace_mcp.git /tmp/workspace-mcp-check
git -C /tmp/workspace-mcp-check describe --tags --exact-match
# Expected: v2.1.0.
uv sync --project /tmp/workspace-mcp-check --frozen --no-dev --extra disk
/tmp/workspace-mcp-check/.venv/bin/python -B tests/stack_80/verify.py \
  --upstream /tmp/workspace-mcp-check
```

## Pending checks on the deployment host

The Docker daemon was not running in this environment. **The image was not
built, and containers were not started**; the Python test does not replace
that verification. OAuth was not completed through the LiteLLM interface.

On the Docker host, complete the settings and follow the README's startup
steps. The user must then register all three MCPs manually, authorize the
personal account, and verify real searches in Drive, Gmail, and Calendar,
write operations using test data, and token refresh through LiteLLM.
The documented OAuth field configuration is a proposal based on LiteLLM's
documentation and the external provider's source, pending that complete
integration test.
