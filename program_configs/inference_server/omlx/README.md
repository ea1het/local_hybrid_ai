<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# oMLX headless Mac mini

This is the **single technical runbook** for the headless oMLX Mac mini.

It replaces the former split between `README.md` and `README.install.md`. The companion [`install.omlx-headless.sh`](install.omlx-headless.sh) is the executable implementation of this document.

Validated baseline:

- Apple Silicon Mac mini
- macOS, headless operation over SSH
- oMLX 0.7.0 validated on 2026-10-01
- normal service account: `norai` on the validated machine; the installer uses the current normal account
- active model directory: `~/.omlx/models`
- external APFS NVMe volume: `/Volumes/NVMe`
- NVMe UUID: `31C10E28-CE2A-410D-B68C-C1D6B3827F5C`
- oMLX SSD cache: `/Volumes/NVMe/AI_Models_Cache`
- oMLX TCP port: `8000`
- persistent Metal/IOGPU wired-memory limit: `60293` MiB

The design goal is not merely "start oMLX at login". The machine must be able to reboot with **no graphical login**, recover its external storage, restore the Metal memory limit, and start oMLX automatically.

TLS for the oMLX endpoint is documented in the [Caddy guide](../caddy/README.md). Certificate issuance and CA distribution are documented in the [mkcert guide](../mkcert/README.md).

## Contents

- [Final architecture](#final-architecture)
- [Why this design exists](#why-this-design-exists)
- [Security and boot assumptions](#security-and-boot-assumptions)
- [Storage layout](#storage-layout)
- [Quick start](#quick-start)
- [Installer actions](#installer-actions)
- [Environment overrides](#environment-overrides)
- [Clean installation](#clean-installation)
- [Update procedure](#update-procedure)
- [Re-apply configuration without upgrading](#re-apply-configuration-without-upgrading)
- [NVMe automount](#nvme-automount)
- [oMLX service model](#omlx-service-model)
- [oMLX configuration policy](#omlx-configuration-policy)
- [Metal / IOGPU memory limit](#metal--iogpu-memory-limit)
- [SSH / Remote Login](#ssh--remote-login)
- [Validation](#validation)
- [Reboot test](#reboot-test)
- [Routine operations](#routine-operations)
- [Logs](#logs)
- [Troubleshooting](#troubleshooting)
- [Upgrade safety rules](#upgrade-safety-rules)

## Final architecture

```text
macOS boot
   |
   +-- FileVault OFF
   |
   +-- local.iogpu-wired-limit
   |      `-- iogpu.wired_limit_mb=60293
   |
   +-- local.mount-nvme
   |      +-- runs at boot
   |      +-- retries if USB/NVMe enumeration is late
   |      +-- mounts by APFS UUID, not /dev/diskN
   |      `-- provides /Volumes/NVMe
   |
   `-- system/sh.brew.omlx
          +-- LaunchDaemon managed by Homebrew
          +-- starts before graphical login
          +-- process runs as the normal account
          +-- HOME = /Users/<user>
          +-- settings = ~/.omlx/settings.json
          +-- models = ~/.omlx/models
          +-- SSD cache = /Volumes/NVMe/AI_Models_Cache
          `-- TCP/8000
```

Homebrew owns the oMLX package and the generated oMLX service.

This repository owns the two machine-level prerequisites that Homebrew does not know about:

```text
/Library/LaunchDaemons/local.iogpu-wired-limit.plist
/Library/LaunchDaemons/local.mount-nvme.plist
/usr/local/sbin/mount-nvme
```

This separation is intentional. A Homebrew package upgrade can replace the oMLX keg without replacing the machine boot policy.

## Why this design exists

Two independent boot-time assumptions caused previous failures.

### 1. External storage was detected but not mounted

The NVMe could be visible to macOS as:

```text
Volume Name: NVMe
Mounted: No
Volume UUID: 31C10E28-CE2A-410D-B68C-C1D6B3827F5C
```

while `/Volumes/NVMe` did not exist.

oMLX 0.7.0 then failed during startup because its SSD cache lived under:

```text
/Volumes/NVMe/AI_Models_Cache
```

and the service received errors such as:

```text
PermissionError: [Errno 13] Permission denied: '/Volumes/NVMe'
```

A manual:

```bash
diskutil mount 31C10E28-CE2A-410D-B68C-C1D6B3827F5C
```

immediately allowed the Homebrew oMLX service to recover on its next launchd retry.

The permanent fix is therefore explicit NVMe automount at system boot.

### 2. The Metal/IOGPU override is not persistent by itself

This command:

```bash
sudo sysctl -w iogpu.wired_limit_mb=60293
```

works only until reboot.

`local.iogpu-wired-limit` reapplies it at every boot.

## Security and boot assumptions

### FileVault

For this specific machine, FileVault is intentionally **off** because the requirement is unattended boot.

Check:

```bash
sudo fdesetup status -extended
```

Expected:

```text
FileVault is Off.
```

If FileVault is enabled, disable it manually only after accepting the security trade-off:

```bash
sudo fdesetup disable
```

Wait for decryption to complete before treating the machine as unattended.

`install.omlx-headless.sh` deliberately **does not disable FileVault automatically**.

### No automatic GUI login

Automatic login is not required.

The server should reach its operational state before any GUI session exists.

### oMLX never runs as root

The package is installed by Homebrew, but the oMLX process runs as the normal server account.

The required service command is:

```bash
sudo brew services start omlx --sudo-service-user="$(id -un)"
```

Do not replace it with either of these:

```bash
brew services start omlx
```

This creates a per-user LaunchAgent and depends on a login session.

```bash
sudo brew services start omlx
```

This runs oMLX as root and causes it to use `/var/root/.omlx`.

## Storage layout

### Internal SSD

Models that must be immediately available after boot live here:

```text
~/.omlx/models
```

This keeps the active model library independent of removable storage.

### External NVMe

Validated volume:

```text
Name:       NVMe
Format:     APFS
Mount:      /Volumes/NVMe
UUID:       31C10E28-CE2A-410D-B68C-C1D6B3827F5C
Encrypted:  No
```

The current oMLX SSD cache lives here:

```text
/Volumes/NVMe/AI_Models_Cache
```

The mount job always addresses the filesystem by UUID because `/dev/diskN` identifiers can change between boots.

## Quick start

From this directory:

```bash
chmod +x install.omlx-headless.sh
./install.omlx-headless.sh install
```

For an existing machine that is already installed and only needs the current headless configuration re-applied:

```bash
./install.omlx-headless.sh configure
```

To upgrade oMLX safely through the stable Homebrew formula:

```bash
./install.omlx-headless.sh update
```

To validate without intentionally changing configuration:

```bash
./install.omlx-headless.sh verify
```

To ask the installed NVMe LaunchDaemon to mount the drive:

```bash
./install.omlx-headless.sh mount
```

Run the script as the normal server account. Do **not** run the complete script with `sudo`.

## Installer actions

### `install`

```bash
./install.omlx-headless.sh install
```

Performs a clean bootstrap:

1. validates Apple Silicon macOS;
2. verifies FileVault is already off;
3. checks Apple Command Line Tools;
4. installs Homebrew if necessary;
5. installs the stable oMLX formula if oMLX is missing;
6. deploys the persistent IOGPU LaunchDaemon;
7. deploys the NVMe automount script and LaunchDaemon;
8. waits for `/Volumes/NVMe`;
9. creates the active-model and SSD-cache directories;
10. creates or patches `~/.omlx/settings.json`;
11. starts oMLX as a system service running as the normal user;
12. validates storage, settings, memory limit, listener and process ownership.

If oMLX is already installed, `install` does not upgrade it.

### `configure`

```bash
./install.omlx-headless.sh configure
```

Re-applies the machine configuration without changing the installed oMLX package version.

Use this after changing this repository's boot policy or after repairing a machine.

### `update`

```bash
./install.omlx-headless.sh update
```

The update workflow:

1. backs up `~/.omlx/settings.json`;
2. stops oMLX;
3. runs `brew update`;
4. ensures the official oMLX tap is present;
5. upgrades the stable formula;
6. if the installed keg is a Homebrew `HEAD-*` build, replaces it with the stable formula;
7. re-deploys the headless prerequisites;
8. re-applies only the settings this server owns;
9. restarts oMLX;
10. runs the complete validation.

A failed package upgrade is **not ignored**. There is no `brew upgrade omlx || true`.

### `verify`

```bash
./install.omlx-headless.sh verify
```

Checks:

- `iogpu.wired_limit_mb`;
- registration of both custom system LaunchDaemons;
- NVMe mount state;
- NVMe cache writeability;
- important oMLX settings;
- TCP/8000 listener;
- listener process ownership.

The API key is not printed.

### `mount`

```bash
./install.omlx-headless.sh mount
```

Kicks the `local.mount-nvme` LaunchDaemon and waits for the expected mount point.

## Environment overrides

Defaults are defined in `install.omlx-headless.sh` and can be overridden per invocation.

Example:

```bash
NVME_UUID="31C10E28-CE2A-410D-B68C-C1D6B3827F5C" \
NVME_MOUNT="/Volumes/NVMe" \
NVME_CACHE_DIR="/Volumes/NVMe/AI_Models_Cache" \
OMLX_PORT=8000 \
./install.omlx-headless.sh configure
```

### Host binding

If `OMLX_HOST` is omitted, the installer preserves the existing `server.host`.

For a new settings file, the safe default is the oMLX loopback default:

```text
127.0.0.1
```

To expose oMLX directly to the LAN:

```bash
OMLX_HOST=0.0.0.0 ./install.omlx-headless.sh configure
```

oMLX 0.7 requires authentication for non-loopback binding. This deployment keeps:

```json
{
  "auth": {
    "skip_api_key_verification": false,
    "allow_unauthenticated_inference": false
  }
}
```

and creates an API key if one does not already exist.

Do not publish the API key in logs or commit it to Git.

## Clean installation

### 1. Confirm architecture

```bash
uname -m
```

Expected:

```text
arm64
```

### 2. Confirm FileVault state

```bash
sudo fdesetup status -extended
```

Expected:

```text
FileVault is Off.
```

### 3. Confirm Command Line Tools

```bash
xcode-select -p
```

If absent:

```bash
xcode-select --install
```

Complete the Apple installer before continuing.

### 4. Run the installer

```bash
chmod +x install.omlx-headless.sh
./install.omlx-headless.sh install
```

### 5. Enable SSH if needed

See [SSH / Remote Login](#ssh--remote-login).

### 6. Perform the mandatory reboot test

See [Reboot test](#reboot-test).

## Update procedure

Never make a routine oMLX upgrade with an undocumented sequence and then assume the old boot behaviour still applies.

Use:

```bash
./install.omlx-headless.sh update
```

The script preserves a timestamped settings backup such as:

```text
~/.omlx/settings.json.backup-20261001-001500
```

It then validates the resulting service.

The script does not promise automatic package rollback. If the new oMLX release itself is broken, the settings backup is available, but restoring an old Homebrew package version may require a separate package-level rollback.

### Stable versus HEAD

A production headless server should normally use the stable Homebrew formula.

Check:

```bash
brew list --versions omlx
```

A path/version containing:

```text
HEAD-
```

means the machine is using a development keg.

`./install.omlx-headless.sh update` detects a `HEAD-*` install and replaces it with the stable formula.

## Re-apply configuration without upgrading

If Homebrew/oMLX is already correct and only the boot plumbing or settings need repair:

```bash
./install.omlx-headless.sh configure
```

This is the preferred operation after editing `install.omlx-headless.sh`.

## NVMe automount

The deployed script is:

```text
/usr/local/sbin/mount-nvme
```

The LaunchDaemon is:

```text
/Library/LaunchDaemons/local.mount-nvme.plist
```

The job:

- runs at boot;
- is retried every 30 seconds;
- waits up to about 60 seconds for the external device to enumerate;
- mounts by APFS UUID;
- exits successfully when the correct mount is available;
- writes only mount attempts/errors to:

```text
/var/log/local.mount-nvme.log
```

The steady-state service is expected to show:

```text
state = not running
last exit code = 0
```

That is correct. It is a short job, not a permanent daemon process.

Check:

```bash
sudo launchctl print system/local.mount-nvme | \
  grep -E 'state =|runs =|last exit code'
```

Check the volume:

```bash
diskutil info 31C10E28-CE2A-410D-B68C-C1D6B3827F5C | \
  grep -E 'Volume Name|Mounted|Mount Point|Volume UUID'
```

Expected:

```text
Volume Name: NVMe
Mounted: Yes
Mount Point: /Volumes/NVMe
Volume UUID: 31C10E28-CE2A-410D-B68C-C1D6B3827F5C
```

## oMLX service model

oMLX remains managed through the Homebrew service definition.

Start:

```bash
sudo brew services start omlx --sudo-service-user="$(id -un)"
```

Stop:

```bash
sudo brew services stop omlx
```

Restart:

```bash
sudo brew services restart omlx --sudo-service-user="$(id -un)"
```

Current deployments can be inspected with:

```bash
sudo launchctl print system/sh.brew.omlx | \
  grep -E 'state =|username =|pid =|last exit code'
```

A previous boot failure can leave:

```text
last exit code = 1
```

visible even while the current process is healthy.

The decisive checks are:

```text
state = running
username = <normal user>
```

plus an actual TCP listener.

Check:

```bash
sudo lsof -nP -iTCP:8000 -sTCP:LISTEN
```

## oMLX configuration policy

The canonical file is:

```text
~/.omlx/settings.json
```

`install.omlx-headless.sh` does not replace the whole file with a hard-coded schema. It loads the installed version's JSON and modifies only the settings owned by this deployment.

### Server

Port:

```json
{
  "server": {
    "port": 8000
  }
}
```

The existing host is preserved unless `OMLX_HOST` is supplied.

### Models

```json
{
  "model": {
    "model_dir": "/Users/<user>/.omlx/models",
    "model_dirs": [
      "/Users/<user>/.omlx/models"
    ],
    "model_fallback": true,
    "hide_helper_models": true
  }
}
```

### SSD cache

```json
{
  "cache": {
    "enabled": true,
    "hot_cache_only": false,
    "ssd_cache_dir": "/Volumes/NVMe/AI_Models_Cache"
  }
}
```

This setting makes NVMe availability a boot dependency. That dependency is why `local.mount-nvme` is part of the final architecture.

### Memory guard

```json
{
  "memory": {
    "prefill_memory_guard": true,
    "memory_guard_tier": "balanced"
  }
}
```

### Authentication

```json
{
  "auth": {
    "skip_api_key_verification": false,
    "allow_unauthenticated_inference": false
  }
}
```

An API key is generated only if none exists.

The installer deliberately does not print it.

To inspect whether a key is configured without printing it:

```bash
python3 - <<'PY'
import json
from pathlib import Path
p = Path.home() / ".omlx/settings.json"
data = json.loads(p.read_text())
print(bool(data.get("auth", {}).get("api_key")))
PY
```

## Metal / IOGPU memory limit

Configured value:

```text
iogpu.wired_limit_mb=60293
```

This is a kernel/Metal ceiling, not memory reserved at boot.

`60293` MiB is the currently validated value for this Mac mini with oMLX 0.7.0. It is an operational baseline, not a universal constant. Future oMLX releases can change the Memory Guard calculation and may recommend a different kernel limit.

Persistence is provided by:

```text
/Library/LaunchDaemons/local.iogpu-wired-limit.plist
```

Check:

```bash
sysctl -n iogpu.wired_limit_mb
```

Expected:

```text
60293
```

Inspect the job:

```bash
sudo launchctl print system/local.iogpu-wired-limit
```

If the live value is wrong, repair the configuration with:

```bash
./install.omlx-headless.sh configure
```

and restart oMLX afterwards if required.

If a future oMLX release explicitly recommends another `iogpu.wired_limit_mb` value, apply that value through the installer rather than with a one-off `sysctl` only:

```bash
IOGPU_LIMIT_MB=<recommended-value> ./install.omlx-headless.sh configure
```

Then restart oMLX and perform the headless reboot test. Once validated, update the default in `install.omlx-headless.sh` and this runbook so the documented baseline matches the deployed machine.

## SSH / Remote Login

Check:

```bash
sudo systemsetup -getremotelogin
```

Enable manually if required:

```bash
sudo systemsetup -setremotelogin on
```

macOS privacy controls can require enabling this through:

```text
System Settings -> General -> Sharing -> Remote Login
```

`install.omlx-headless.sh` deliberately does not change Remote Login automatically.

## Validation

Run:

```bash
./install.omlx-headless.sh verify
```

Manual equivalent:

```bash
echo "=== IOGPU ==="
sysctl -n iogpu.wired_limit_mb

echo
echo "=== NVME ==="
diskutil info 31C10E28-CE2A-410D-B68C-C1D6B3827F5C | \
  grep -E 'Volume Name|Mounted|Mount Point|Volume UUID'

echo
echo "=== MOUNT DAEMON ==="
sudo launchctl print system/local.mount-nvme | \
  grep -E 'state =|runs =|last exit code'

echo
echo "=== OMLX ==="
sudo launchctl print system/sh.brew.omlx | \
  grep -E 'state =|username =|pid =|last exit code'

echo
echo "=== PORT 8000 ==="
sudo lsof -nP -iTCP:8000 -sTCP:LISTEN
```

Healthy output has these properties:

```text
iogpu.wired_limit_mb = 60293

NVMe:
  Mounted: Yes
  Mount Point: /Volumes/NVMe

local.mount-nvme:
  last exit code = 0

oMLX:
  state = running
  username = <normal user>

TCP/8000:
  LISTEN
```

## Reboot test

This test is mandatory after first installation and after changing boot plumbing.

Reboot:

```bash
sudo reboot
```

Do **not** log in graphically.

Reconnect using SSH and run:

```bash
./install.omlx-headless.sh verify
```

The validated boot sequence on 2026-10-01 showed the NVMe initially unavailable, detected a few seconds later, mounted it automatically, and then oMLX recovered and reached `state = running`.

That is the behaviour this runbook is designed to preserve.

## Routine operations

### Check status

```bash
./install.omlx-headless.sh verify
```

### Reconfigure

```bash
./install.omlx-headless.sh configure
```

### Upgrade

```bash
./install.omlx-headless.sh update
```

### Mount NVMe

```bash
./install.omlx-headless.sh mount
```

or:

```bash
diskutil mount 31C10E28-CE2A-410D-B68C-C1D6B3827F5C
```

### Safe NVMe unmount

Because oMLX uses the NVMe as its SSD cache, stop oMLX before unmounting:

```bash
sudo brew services stop omlx
diskutil unmount 31C10E28-CE2A-410D-B68C-C1D6B3827F5C
```

To restore service:

```bash
./install.omlx-headless.sh mount
sudo brew services start omlx --sudo-service-user="$(id -un)"
```

### Shell aliases

`install.omlx-headless.sh` manages this block in `~/.zshrc`:

```bash
alias l='ls -l'
alias ll='ls -lash'
alias disk='df -h'
alias nvme='diskutil mount 31C10E28-CE2A-410D-B68C-C1D6B3827F5C'
alias unvme='diskutil unmount 31C10E28-CE2A-410D-B68C-C1D6B3827F5C'
alias cdnvme='cd /Volumes/NVMe'
```

Reload:

```bash
source ~/.zshrc
```

## Logs

### Homebrew oMLX stdout/stderr

```text
/opt/homebrew/var/log/omlx.log
```

Inspect:

```bash
tail -100 /opt/homebrew/var/log/omlx.log
```

### oMLX application log

```text
~/.omlx/logs/server.log
```

Inspect:

```bash
tail -100 ~/.omlx/logs/server.log
```

### NVMe automount log

```text
/var/log/local.mount-nvme.log
```

Inspect:

```bash
sudo tail -100 /var/log/local.mount-nvme.log
```

## Troubleshooting

### NVMe is visible but not mounted

Check:

```bash
diskutil list
diskutil info 31C10E28-CE2A-410D-B68C-C1D6B3827F5C
```

If it reports:

```text
Mounted: No
```

try:

```bash
./install.omlx-headless.sh mount
```

Then inspect:

```bash
sudo tail -100 /var/log/local.mount-nvme.log
```

### `/Volumes/NVMe` does not exist

That is normal when the volume is not mounted.

Do not create `/Volumes/NVMe` manually as a substitute for mounting the APFS volume.

### oMLX exits with `PermissionError: /Volumes/NVMe`

Check the NVMe first:

```bash
diskutil info 31C10E28-CE2A-410D-B68C-C1D6B3827F5C | \
  grep -E 'Mounted|Mount Point'
```

Then:

```bash
./install.omlx-headless.sh mount
```

The Homebrew system service normally retries automatically. Verify afterwards:

```bash
sudo lsof -nP -iTCP:8000 -sTCP:LISTEN
```

### oMLX service is running but `last exit code = 1`

`launchctl` can retain the exit status of a previous failed launch.

If all of these are true:

```text
state = running
username = <normal user>
TCP/8000 = LISTEN
```

the current process is healthy.

### oMLX binds only to loopback

Check:

```bash
sudo lsof -nP -iTCP:8000 -sTCP:LISTEN
```

`127.0.0.1:8000` is local-only.

If direct LAN access is required:

```bash
OMLX_HOST=0.0.0.0 ./install.omlx-headless.sh configure
```

Keep API-key verification enabled.

### oMLX refuses non-loopback startup after an upgrade

Check the authentication block in:

```text
~/.omlx/settings.json
```

The supported headless policy is:

```json
{
  "auth": {
    "skip_api_key_verification": false,
    "allow_unauthenticated_inference": false
  }
}
```

Repair:

```bash
./install.omlx-headless.sh configure
```

### Homebrew path contains `HEAD-*`

Check:

```bash
brew list --versions omlx
readlink /opt/homebrew/opt/omlx
```

Use:

```bash
./install.omlx-headless.sh update
```

to move the deployment back to the stable formula.

### Admin UI templates are missing after a Homebrew update

Errors such as:

```text
jinja2.exceptions.TemplateNotFound: dashboard.html
```

can indicate a broken/incomplete package keg rather than a launchd problem.

First check whether the package is a `HEAD-*` build, then use:

```bash
./install.omlx-headless.sh update
```

and revalidate.

## Upgrade safety rules

These are the invariants for future maintenance.

1. **Never depend on a versioned Cellar path.**

   Use the Homebrew `opt` symlink or Homebrew service management.

2. **Do not run oMLX as root.**

   The service must use:

   ```bash
   sudo brew services start omlx --sudo-service-user="$(id -un)"
   ```

3. **Do not assume the NVMe is mounted because macOS can see the disk.**

   `diskutil list` can show the device while the APFS volume remains `Mounted: No`.

4. **Mount external storage by filesystem UUID, not `/dev/diskN`.**

5. **Treat the NVMe as a boot dependency while `cache.ssd_cache_dir` points to it.**

6. **Back up `settings.json` before an oMLX package update.**

7. **Do not swallow package-upgrade failures.**

8. **Prefer stable Homebrew releases for the headless server.**

9. **Preserve API authentication when binding to a non-loopback address.**

10. **After any boot-policy or package change, reboot without GUI login and run:**

    ```bash
    ./install.omlx-headless.sh verify
    ```

A change is not considered complete until that headless reboot test passes.
