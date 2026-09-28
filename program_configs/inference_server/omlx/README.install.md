<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Install oMLX on a headless Mac mini

[Configuration and operations](README.md) · [Installer script](install.sh) · [Caddy TLS setup](../caddy/README.md) · [mkcert and CA setup](../mkcert/README.md)

This document describes, command by command, how to take a clean Apple Silicon macOS installation to the known-working headless oMLX configuration.

The companion [`install.sh`](install.sh) automates these steps. This document exists so that every change made by the script is explicit and reproducible.

The validated account name is norai. The installer automatically uses the account that executes it, so run it while logged in as the normal server account. Do not run the whole installer with sudo.

## 1. Requirements

The target is an Apple Silicon Mac running macOS with:

one normal local user account;

no requirement for automatic GUI login;

network connectivity;

oMLX served over the LAN on TCP/8000;

64 GB unified memory for the 59392 MiB IOGPU setting used here.

Confirm the architecture:

uname -m

Expected:

arm64

## 2. Disable FileVault

Check:

sudo fdesetup status -extended

For this unattended server the expected state is:

FileVault is Off.

If FileVault is enabled:

sudo fdesetup disable

Why: with FileVault active, a reboot can stop at the pre-boot authentication stage. In testing, SSH could only unlock the system, after which the connection closed and macOS continued booting. oMLX cannot start before the encrypted system volume is unlocked.

Wait until:

sudo fdesetup status -extended

reports FileVault off before treating the machine as unattended.

## 3. Install Apple Command Line Tools

Check:

xcode-select -p

If the tools are absent:

xcode-select --install

Finish the Apple installer before continuing.

These tools are required by Homebrew.

## 4. Install Homebrew

Check:

command -v brew

On Apple Silicon Homebrew normally lives under:

/opt/homebrew

Install it if necessary:

/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

Load it into the current shell:

eval "$(/opt/homebrew/bin/brew shellenv)"

## 5. Install oMLX

Add the official oMLX tap:

brew tap jundot/omlx https://github.com/jundot/omlx

Install:

brew install jundot/omlx/omlx

Upgrade later with:

brew update
brew upgrade omlx

The known-working machine originally used oMLX 0.6.4. The installer intentionally uses the current Homebrew formula rather than hard-pinning an old Cellar path.

## 6. Create the internal active-model directory

mkdir -p ~/.omlx/models

This is the directory used for models that must be available at unattended boot.

Do not configure /Volumes/NVMe/AI_Models_Storage as an always-on oMLX model directory. macOS denied that pre-login LaunchDaemon access with:

Operation not permitted

even though normal Unix permissions were correct.

## 7. Configure the persistent IOGPU wired-memory limit

The live command is:

sudo sysctl -w iogpu.wired_limit_mb=59392

This works only until the next reboot.

To persist it, create:

sudo tee /Library/LaunchDaemons/local.iogpu-wired-limit.plist >/dev/null <<'EOF'
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
        <string>iogpu.wired_limit_mb=59392</string>
    </array>

    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
EOF

Set ownership and permissions:

sudo chown root:wheel /Library/LaunchDaemons/local.iogpu-wired-limit.plist
sudo chmod 644 /Library/LaunchDaemons/local.iogpu-wired-limit.plist

Validate:

sudo plutil -lint /Library/LaunchDaemons/local.iogpu-wired-limit.plist

Load it:

sudo launchctl bootstrap system   /Library/LaunchDaemons/local.iogpu-wired-limit.plist

Apply the value immediately:

sudo sysctl -w iogpu.wired_limit_mb=59392

Verify:

sysctl -n iogpu.wired_limit_mb

Expected:

59392

If it returns 0, the override is not active and oMLX will fall back to Apple's default Metal working-set limit.

## 8. Create the initial oMLX configuration

Remove any accidental user service or root-running service:

brew services stop omlx 2>/dev/null || true
sudo brew services stop omlx 2>/dev/null || true

Start oMLX correctly once:

sudo brew services start omlx --sudo-service-user="$(id -un)"

This creates a system service while the oMLX process itself runs as the normal account.

Verify:

sudo launchctl print system/sh.brew.omlx |   grep -E 'state =|username =|pid ='

The important line is:

username = norai

If the service is started with sudo brew services start omlx without --sudo-service-user, it runs as root and uses /var/root/.omlx. That is the wrong configuration.

## 9. Configure LAN listening and local model storage

oMLX stores global configuration in:

~/.omlx/settings.json

The installer starts oMLX once so the installed version creates its own settings schema, stops it, and modifies only the required keys.

The intended values are:

{
  "server": {
    "host": "0.0.0.0",
    "port": 8000
  },
  "model": {
    "model_dirs": [
      "/Users/norai/.omlx/models"
    ]
  }
}

The installer also:

enables fallback to the default model;

hides helper models from /v1/models;

keeps the memory guard enabled in balanced mode;

keeps hot_cache_only disabled;

enables the normal Hugging Face local cache;

creates an API key if no API key already exists.

The API key is printed at the end for LiteLLM or other clients.

## 10. Start oMLX as the final system service

The final start command is:

sudo brew services start omlx --sudo-service-user="$(id -un)"

Check:

sudo launchctl print system/sh.brew.omlx |   grep -E 'state =|username =|pid ='

Expected:

state = running
username = norai
pid = ...

Check TCP/8000:

sudo lsof -nP -iTCP:8000 -sTCP:LISTEN

Expected:

Python ... norai ... TCP *:8000 (LISTEN)

A listener on 127.0.0.1:8000 is local-only.

## 11. Configure shell shortcuts

Append to ~/.zshrc:

alias l='ls -l'
alias ll='ls -lash'
alias disk='df -h'

alias nvme='diskutil mount 31C10E28-CE2A-410D-B68C-C1D6B3827F5C'
alias unvme='diskutil unmount 31C10E28-CE2A-410D-B68C-C1D6B3827F5C'
alias cdnvme='cd /Volumes/NVMe'

Reload:

source ~/.zshrc

The NVMe UUID is used instead of /dev/diskN because disk identifiers can change between boots.

## 12. Remote Login / SSH

Check:

sudo systemsetup -getremotelogin

Enable if necessary:

sudo systemsetup -setremotelogin on

If macOS rejects the command because of privacy controls, enable Remote Login manually under:

System Settings -> General -> Sharing -> Remote Login

No automatic GUI login is required.

## 13. Reboot validation

Reboot:

sudo reboot

Do not perform a graphical login.

Connect directly by SSH and check:

sysctl -n iogpu.wired_limit_mb

Expected:

59392

Then:

sudo launchctl print system/sh.brew.omlx |   grep -E 'state =|username =|pid ='

Expected:

state = running
username = norai
pid = ...

Then:

sudo lsof -nP -iTCP:8000 -sTCP:LISTEN

Expected:

Python ... norai ... TCP *:8000 (LISTEN)

If the sysctl is correct but oMLX still shows the old/default Metal ceiling, restart oMLX:

sudo brew services restart omlx --sudo-service-user="$(id -un)"

## 14. NVMe manual use

Mount:

nvme

Verify:

mount | grep /Volumes/NVMe

Enter:

cdnvme

Unmount:

unvme

The final design intentionally has no NVMe automount LaunchDaemon.

## 15. Things intentionally not installed

The final configuration does not use:

local.omlx
local.mount-nvme
com.local.iogpu-wired-limit

It also does not use:

automatic GUI login;

Full Disk Access for python3.11;

a custom .app wrapper;

a shell loop waiting for the NVMe;

an oMLX PathState dependency.

The only custom LaunchDaemon is:

local.iogpu-wired-limit

Everything else is managed by Homebrew and oMLX.
