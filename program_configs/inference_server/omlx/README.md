<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# oMLX headless Mac mini

Use this page for the deployed configuration and routine checks. For a clean installation, use [`install.sh`](install.sh) and follow the [installation and reboot checklist](README.install.md). TLS for the oMLX endpoint is covered by the [Caddy guide](../caddy/README.md); certificate issuance and CA distribution are covered by the [mkcert guide](../mkcert/README.md).

This repository documents the working, minimal configuration of the Mac mini used as a headless oMLX inference server.

The goal is simple:

macOS boots without requiring a GUI login.

oMLX starts automatically at boot.

oMLX runs as the normal account (norai), not as root.

oMLX listens on the LAN on TCP/8000.

active models live on the internal SSD under ~/.omlx/models.

the Thunderbolt NVMe is mounted manually when needed.

the Metal/IOGPU wired-memory limit is raised persistently to 59392 MiB.

no automatic login, no Full Disk Access exception for Python, no oMLX wrapper app, and no NVMe automount daemon.

## Final architecture

macOS boot
   |
   +-- FileVault OFF
   |
   +-- local.iogpu-wired-limit
   |      `-- iogpu.wired_limit_mb=59392
   |
   `-- system/sh.brew.omlx
          |
          +-- LaunchDaemon managed by Homebrew
          +-- starts without GUI login
          +-- process runs as user norai
          +-- HOME = /Users/norai
          +-- settings = /Users/norai/.omlx/settings.json
          +-- models = /Users/norai/.omlx/models
          `-- TCP *:8000

The critical oMLX service command is:

sudo brew services start omlx --sudo-service-user=norai

That exact combination matters.

Running:

sudo brew services start omlx

starts the service as root, causing oMLX to use /var/root/.omlx.

Running:

brew services start omlx

creates a per-user LaunchAgent, which depends on a user login session.

The working configuration is a system LaunchDaemon that executes as norai.

## FileVault

FileVault is intentionally disabled.

With FileVault enabled, the Mac stopped at the pre-boot unlock stage and the first SSH connection only unlocked the machine:

System successfully unlocked.
You may now use SSH to authenticate normally.

That is incompatible with a genuinely unattended inference server.

Check:

sudo fdesetup status -extended

Expected:

FileVault is Off.

No automatic GUI login is configured.

## oMLX

oMLX is installed with Homebrew:

brew tap jundot/omlx https://github.com/jundot/omlx
brew install jundot/omlx/omlx

The configuration lives in:

~/.omlx/settings.json

The intended server endpoint is:

http://<mac-mini-ip>:8000

The service must show:

state = running
username = norai

Verify with:

sudo launchctl print system/sh.brew.omlx | grep -E 'state =|username =|pid ='

Verify the listener:

sudo lsof -nP -iTCP:8000 -sTCP:LISTEN

Expected:

Python ... norai ... TCP *:8000 (LISTEN)

## Active model storage

Models that must be available immediately after boot live on the internal SSD:

/Users/norai/.omlx/models

This is deliberate.

The external Thunderbolt NVMe was tested as an oMLX model directory at:

/Volumes/NVMe/AI_Models_Storage

The directory itself was readable interactively by norai, but a pre-login LaunchDaemon received:

PermissionError: [Errno 1] Operation not permitted

from macOS when oMLX attempted to scan it.

Because oMLX 0.6.4 removes unavailable model directories from settings.json, the external volume is not used for always-on model serving.

The NVMe remains useful as manual/archive storage.

## Thunderbolt NVMe

Volume name:

NVMe

APFS Volume UUID:

31C10E28-CE2A-410D-B68C-C1D6B3827F5C

It is mounted manually:

nvme

Unmount:

unvme

Enter the volume:

cdnvme

The aliases are installed in ~/.zshrc.

## Shell aliases

l        -> ls -l
ll       -> ls -lash
disk     -> df -h
nvme     -> mount NVMe by APFS UUID
unvme    -> unmount NVMe by APFS UUID
cdnvme   -> cd /Volumes/NVMe

Reload them after editing .zshrc:

source ~/.zshrc

## Metal / IOGPU memory limit

The server uses:

iogpu.wired_limit_mb=59392

59392 MiB is 58 GiB.

This is a ceiling, not memory immediately reserved at boot.

The setting is not persistent by itself. Running only:

sudo sysctl -w iogpu.wired_limit_mb=59392

is lost after reboot.

Persistence is provided by:

/Library/LaunchDaemons/local.iogpu-wired-limit.plist

Check the live value:

sysctl -n iogpu.wired_limit_mb

Expected:

59392

If it returns:

0

oMLX falls back to Apple's default Metal working-set limit, which on this machine was displayed around 51.8 GB.

After correcting the sysctl, restart oMLX so that the process starts with the intended Metal limit:

sudo brew services restart omlx --sudo-service-user=norai

## Logs

Homebrew service stdout/stderr:

/opt/homebrew/var/log/omlx.log

oMLX application log:

~/.omlx/logs/server.log

Useful commands:

tail -100 /opt/homebrew/var/log/omlx.log
tail -100 ~/.omlx/logs/server.log

## Service maintenance

Start correctly:

sudo brew services start omlx --sudo-service-user=norai

Stop:

sudo brew services stop omlx

Restart correctly:

sudo brew services restart omlx --sudo-service-user=norai

Do not replace the start command with a plain sudo brew services start omlx.

## Reinstall

For a clean Mac, use:

chmod +x install.sh
./install.sh

For command-by-command setup and prerequisites, use the [manual installation guide](README.install.md).

After installation, reboot the Mac and do not log in graphically. Connect by SSH and validate:

sysctl -n iogpu.wired_limit_mb

sudo launchctl print system/sh.brew.omlx |   grep -E 'state =|username =|pid ='

sudo lsof -nP -iTCP:8000 -sTCP:LISTEN

Expected:

59392
state = running
username = norai
Python ... norai ... TCP *:8000 (LISTEN)
