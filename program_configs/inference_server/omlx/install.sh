#!/bin/bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -Eeuo pipefail

# Minimal bootstrap for the known-working headless oMLX Mac mini configuration.
# Run as the normal server account, NOT with: sudo ./install.sh

IOGPU_LIMIT_MB="${IOGPU_LIMIT_MB:-59392}"
NVME_UUID="${NVME_UUID:-31C10E28-CE2A-410D-B68C-C1D6B3827F5C}"
OMLX_PORT="${OMLX_PORT:-8000}"

say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

[[ "$(uname -s)" == "Darwin" ]] || die "macOS required."
[[ "$(uname -m)" == "arm64" ]] || die "Apple Silicon required."
[[ "${EUID}" -ne 0 ]] || die "Run this script as the normal server user, not with sudo."

USER_NAME="$(id -un)"
USER_HOME="$(dscl . -read "/Users/${USER_NAME}" NFSHomeDirectory | awk '{print $2}')"
MODEL_DIR="${USER_HOME}/.omlx/models"
SETTINGS="${USER_HOME}/.omlx/settings.json"
ZSHRC="${USER_HOME}/.zshrc"

say "Using account: ${USER_NAME}"
sudo -v

# FileVault must be off for unattended boot.
if ! sudo fdesetup status 2>/dev/null | grep -q "FileVault is Off"; then
  say "Disabling FileVault"
  sudo fdesetup disable
  if ! sudo fdesetup status 2>/dev/null | grep -q "FileVault is Off"; then
    echo
    echo "FileVault decryption has started but is not finished."
    echo "Wait until 'sudo fdesetup status -extended' reports FileVault Off,"
    echo "then run ./install.sh again."
    exit 2
  fi
fi

# Apple Command Line Tools.
if ! xcode-select -p >/dev/null 2>&1; then
  say "Requesting Apple Command Line Tools"
  xcode-select --install || true
  echo "Finish the Apple installer, then run ./install.sh again."
  exit 2
fi

# Homebrew.
if ! command -v brew >/dev/null 2>&1; then
  say "Installing Homebrew"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

eval "$(/opt/homebrew/bin/brew shellenv)"
BREW="/opt/homebrew/bin/brew"

# oMLX.
say "Installing oMLX"
"${BREW}" tap jundot/omlx https://github.com/jundot/omlx
if "${BREW}" list --formula omlx >/dev/null 2>&1; then
  "${BREW}" upgrade omlx || true
else
  "${BREW}" install jundot/omlx/omlx
fi

mkdir -p "${MODEL_DIR}"

# Persistent IOGPU wired limit.
say "Configuring iogpu.wired_limit_mb=${IOGPU_LIMIT_MB}"
sudo launchctl bootout system/local.iogpu-wired-limit >/dev/null 2>&1 || true

sudo tee /Library/LaunchDaemons/local.iogpu-wired-limit.plist >/dev/null <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>local.iogpu-wired-limit</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/sbin/sysctl</string>
        <string>-w</string>
        <string>iogpu.wired_limit_mb=${IOGPU_LIMIT_MB}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
EOF

sudo chown root:wheel /Library/LaunchDaemons/local.iogpu-wired-limit.plist
sudo chmod 644 /Library/LaunchDaemons/local.iogpu-wired-limit.plist
sudo plutil -lint /Library/LaunchDaemons/local.iogpu-wired-limit.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/local.iogpu-wired-limit.plist
sudo sysctl -w "iogpu.wired_limit_mb=${IOGPU_LIMIT_MB}"

# Remove any wrong oMLX service instance, then start correctly once so that
# the installed oMLX version creates its own settings schema.
say "Creating oMLX settings"
"${BREW}" services stop omlx >/dev/null 2>&1 || true
sudo "${BREW}" services stop omlx >/dev/null 2>&1 || true
sudo "${BREW}" services start omlx --sudo-service-user="${USER_NAME}"

for _ in $(seq 1 30); do
  [[ -f "${SETTINGS}" ]] && break
  sleep 1
done
[[ -f "${SETTINGS}" ]] || die "oMLX did not create ${SETTINGS}."

sudo "${BREW}" services stop omlx

# Modify only the settings required by this server.
OMLX_BIN="$("${BREW}" --prefix omlx)/bin/omlx"
OMLX_PYTHON="$(sed -n '1s/^#!//p' "${OMLX_BIN}")"
[[ -x "${OMLX_PYTHON}" ]] || die "Cannot resolve oMLX Python interpreter."

export SETTINGS MODEL_DIR OMLX_PORT
NEW_API_KEY="$("${OMLX_PYTHON}" -c 'import secrets; print(secrets.token_urlsafe(32))')"
export NEW_API_KEY

"${OMLX_PYTHON}" <<'PY'
import json
import os
from pathlib import Path

p = Path(os.environ["SETTINGS"])
data = json.loads(p.read_text())

server = data.setdefault("server", {})
server["host"] = "0.0.0.0"
server["port"] = int(os.environ["OMLX_PORT"])

model = data.setdefault("model", {})
model["model_dirs"] = [os.environ["MODEL_DIR"]]
model["model_dir"] = os.environ["MODEL_DIR"]
model["model_fallback"] = True
model["hide_helper_models"] = True

memory = data.setdefault("memory", {})
memory["prefill_memory_guard"] = True
memory["memory_guard_tier"] = "balanced"

cache = data.setdefault("cache", {})
cache["hot_cache_only"] = False

hf = data.setdefault("huggingface", {})
hf["hf_cache_enabled"] = True

auth = data.setdefault("auth", {})
if not auth.get("api_key"):
    auth["api_key"] = os.environ["NEW_API_KEY"]
auth["skip_api_key_verification"] = False

tmp = p.with_name(p.name + ".install-tmp")
tmp.write_text(json.dumps(data, indent=2) + "\n")
tmp.chmod(0o600)
tmp.replace(p)
PY

chmod 600 "${SETTINGS}"

# Start the FINAL oMLX system service as the normal account.
say "Starting oMLX as a system service running as ${USER_NAME}"
sudo "${BREW}" services start omlx --sudo-service-user="${USER_NAME}"

# zsh shortcuts.
say "Installing shell aliases"
touch "${ZSHRC}"

export ZSHRC NVME_UUID
"${OMLX_PYTHON}" <<'PY'
from pathlib import Path
import os
import re

p = Path(os.environ["ZSHRC"])
uuid = os.environ["NVME_UUID"]
text = p.read_text() if p.exists() else ""

start = "# >>> omlx-headless shortcuts >>>"
end = "# <<< omlx-headless shortcuts <<<"

block = (
    start + "\n"
    "alias l='ls -l'\n"
    "alias ll='ls -lash'\n"
    "alias disk='df -h'\n"
    f"alias nvme='diskutil mount {uuid}'\n"
    f"alias unvme='diskutil unmount {uuid}'\n"
    "alias cdnvme='cd /Volumes/NVMe'\n"
    + end
)

pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
if pattern.search(text):
    text = pattern.sub(block, text)
else:
    if text and not text.endswith("\n"):
        text += "\n"
    text += "\n" + block + "\n"

p.write_text(text)
PY

# Enable SSH if systemsetup permits it.
say "Checking Remote Login"
if sudo /usr/sbin/systemsetup -getremotelogin 2>/dev/null | grep -qi "Off"; then
  sudo /usr/sbin/systemsetup -setremotelogin on >/dev/null 2>&1 || \
    echo "WARNING: enable System Settings -> General -> Sharing -> Remote Login manually."
fi

# Validation.
say "Validating"
LIVE_LIMIT="$(sysctl -n iogpu.wired_limit_mb)"
[[ "${LIVE_LIMIT}" == "${IOGPU_LIMIT_MB}" ]] || die "IOGPU limit is ${LIVE_LIMIT}, expected ${IOGPU_LIMIT_MB}."

SERVICE="$(sudo launchctl print system/sh.brew.omlx 2>/dev/null || true)"
grep -q "state = running" <<<"${SERVICE}" || die "oMLX service is not running."
grep -q "username = ${USER_NAME}" <<<"${SERVICE}" || die "oMLX is not running as ${USER_NAME}."

for _ in $(seq 1 30); do
  if sudo lsof -nP -iTCP:"${OMLX_PORT}" -sTCP:LISTEN 2>/dev/null | grep -q LISTEN; then
    break
  fi
  sleep 1
done

sudo lsof -nP -iTCP:"${OMLX_PORT}" -sTCP:LISTEN 2>/dev/null | grep -q LISTEN \
  || die "Nothing is listening on TCP/${OMLX_PORT}."

FINAL_KEY="$("${OMLX_PYTHON}" - "${SETTINGS}" <<'PY'
import json, sys
print(json.load(open(sys.argv[1]))["auth"].get("api_key", ""))
PY
)"

cat <<EOF

============================================================
INSTALLATION COMPLETE
============================================================

User:               ${USER_NAME}
Models:             ${MODEL_DIR}
oMLX:               http://<this-mac-ip>:${OMLX_PORT}
IOGPU wired limit:  ${LIVE_LIMIT} MiB
Settings:           ${SETTINGS}

API key:
${FINAL_KEY}

Reboot once, do NOT log in graphically, then verify over SSH:

  sysctl -n iogpu.wired_limit_mb

  sudo launchctl print system/sh.brew.omlx | \
    grep -E 'state =|username =|pid ='

  sudo lsof -nP -iTCP:${OMLX_PORT} -sTCP:LISTEN

Expected:
- iogpu.wired_limit_mb = ${IOGPU_LIMIT_MB}
- oMLX state = running
- oMLX username = ${USER_NAME}
- TCP *:${OMLX_PORT} is listening

NVMe remains manual:
  nvme
  unvme
  cdnvme

If the IOGPU value is correct after reboot but the oMLX UI still shows
the old/default Metal ceiling, restart oMLX once with:

  sudo brew services restart omlx --sudo-service-user=${USER_NAME}

============================================================
EOF
