#!/bin/bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -Eeuo pipefail

# Headless oMLX bootstrap/configuration for Apple Silicon macOS.
# Run as the normal server account, never as root:
#
#   ./install.omlx-headless.sh install
#   ./install.omlx-headless.sh configure
#   ./install.omlx-headless.sh update
#   ./install.omlx-headless.sh verify
#   ./install.omlx-headless.sh mount
#
# Environment overrides:
#   IOGPU_LIMIT_MB=60293
#   NVME_UUID=31C10E28-CE2A-410D-B68C-C1D6B3827F5C
#   NVME_MOUNT=/Volumes/NVMe
#   NVME_CACHE_DIR=/Volumes/NVMe/AI_Models_Cache
#   OMLX_HOST=127.0.0.1     # omit to preserve an existing host setting
#   OMLX_PORT=8000

ACTION="${1:-install}"

IOGPU_LIMIT_MB="${IOGPU_LIMIT_MB:-60293}"
NVME_UUID="${NVME_UUID:-31C10E28-CE2A-410D-B68C-C1D6B3827F5C}"
NVME_MOUNT="${NVME_MOUNT:-/Volumes/NVMe}"
NVME_CACHE_DIR="${NVME_CACHE_DIR:-${NVME_MOUNT}/AI_Models_Cache}"
OMLX_HOST="${OMLX_HOST:-}"
OMLX_PORT="${OMLX_PORT:-8000}"

say() { printf '\n==> %s\n' "$*"; }
warn() { printf '\nWARNING: %s\n' "$*" >&2; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage:
  ./install.omlx-headless.sh install      Install stable oMLX if missing, deploy headless config, start and verify
  ./install.omlx-headless.sh configure    Re-apply headless config without changing the installed oMLX version
  ./install.omlx-headless.sh update       Backup settings, move HEAD installs to stable, upgrade oMLX, reconfigure and verify
  ./install.omlx-headless.sh verify       Read-only validation of the deployed headless configuration
  ./install.omlx-headless.sh mount        Ask the NVMe LaunchDaemon to mount the configured external volume

Run as the normal server account, not with sudo.

Optional environment overrides:
  IOGPU_LIMIT_MB
  NVME_UUID
  NVME_MOUNT
  NVME_CACHE_DIR
  OMLX_HOST               (if omitted, preserve existing value; new installs default to 127.0.0.1)
  OMLX_PORT
EOF
}

case "${ACTION}" in
  install|configure|update|verify|mount) ;;
  -h|--help|help) usage; exit 0 ;;
  *) usage; die "Unknown action: ${ACTION}" ;;
esac

[[ "$(uname -s)" == "Darwin" ]] || die "macOS required."
[[ "$(uname -m)" == "arm64" ]] || die "Apple Silicon required."
[[ "${EUID}" -ne 0 ]] || die "Run as the normal server account, not with sudo."

USER_NAME="$(id -un)"
USER_GROUP="$(id -gn)"
USER_HOME="$(dscl . -read "/Users/${USER_NAME}" NFSHomeDirectory | awk '{print $2}')"
MODEL_DIR="${USER_HOME}/.omlx/models"
SETTINGS="${USER_HOME}/.omlx/settings.json"
ZSHRC="${USER_HOME}/.zshrc"

BREW="/opt/homebrew/bin/brew"
MOUNT_SCRIPT="/usr/local/sbin/mount-nvme"
MOUNT_PLIST="/Library/LaunchDaemons/local.mount-nvme.plist"
IOGPU_PLIST="/Library/LaunchDaemons/local.iogpu-wired-limit.plist"
MOUNT_LOG="/var/log/local.mount-nvme.log"

sudo -v

check_filevault() {
  local status
  status="$(sudo fdesetup status 2>/dev/null || true)"
  if ! grep -q "FileVault is Off" <<<"${status}"; then
    cat >&2 <<'EOF'

FileVault is not fully disabled.

A genuinely unattended Mac cannot complete a normal macOS boot while the
system volume is waiting at pre-boot FileVault unlock. This installer will
not disable disk encryption automatically.

If unattended boot is intentional for this machine:
  sudo fdesetup disable

Wait until:
  sudo fdesetup status -extended

reports FileVault is Off, then rerun this script.
EOF
    exit 2
  fi
}

ensure_clt() {
  if ! xcode-select -p >/dev/null 2>&1; then
    xcode-select --install || true
    die "Finish the Apple Command Line Tools installation, then rerun."
  fi
}

ensure_homebrew() {
  if [[ ! -x "${BREW}" ]]; then
    say "Installing Homebrew"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  fi
  [[ -x "${BREW}" ]] || die "Homebrew not found at ${BREW}."
  eval "$("${BREW}" shellenv)"
}

omlx_installed() {
  "${BREW}" list --formula omlx >/dev/null 2>&1
}

omlx_prefix() {
  "${BREW}" --prefix omlx
}

omlx_is_head() {
  "${BREW}" list --versions omlx 2>/dev/null | /usr/bin/grep -q 'HEAD-'
}

stop_omlx() {
  "${BREW}" services stop omlx >/dev/null 2>&1 || true
  sudo "${BREW}" services stop omlx >/dev/null 2>&1 || true
}

install_omlx_if_missing() {
  say "Ensuring stable oMLX is installed"
  "${BREW}" tap jundot/omlx https://github.com/jundot/omlx

  if omlx_installed; then
    say "oMLX already installed; install mode will not upgrade it"
    return
  fi

  "${BREW}" install jundot/omlx/omlx
}

backup_settings() {
  [[ -f "${SETTINGS}" ]] || return 0

  local backup
  backup="${SETTINGS}.backup-$(date '+%Y%m%d-%H%M%S')"
  cp -p "${SETTINGS}" "${backup}"
  say "Backed up settings to ${backup}"
}

update_omlx_stable() {
  say "Updating oMLX stable channel"
  [[ -x "${BREW}" ]] || die "Homebrew is not installed."
  omlx_installed || die "oMLX is not installed. Run: ./install.omlx-headless.sh install"

  backup_settings
  stop_omlx

  "${BREW}" update
  "${BREW}" tap jundot/omlx https://github.com/jundot/omlx

  if omlx_is_head; then
    say "Detected a Homebrew HEAD keg; replacing it with the stable formula"
    "${BREW}" uninstall --force omlx
    "${BREW}" install jundot/omlx/omlx
  else
    "${BREW}" upgrade omlx
  fi
}

resolve_python() {
  local prefix candidate
  prefix="$(omlx_prefix)"

  for candidate in \
    "${prefix}/libexec/bin/python" \
    "${prefix}/libexec/bin/python3" \
    "/usr/bin/python3"
  do
    if [[ -x "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done

  die "Cannot find a Python interpreter for settings maintenance."
}

configure_iogpu() {
  say "Configuring persistent iogpu.wired_limit_mb=${IOGPU_LIMIT_MB}"

  sudo launchctl bootout system/local.iogpu-wired-limit >/dev/null 2>&1 || true

  sudo tee "${IOGPU_PLIST}" >/dev/null <<EOF
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

  sudo chown root:wheel "${IOGPU_PLIST}"
  sudo chmod 644 "${IOGPU_PLIST}"
  sudo plutil -lint "${IOGPU_PLIST}" >/dev/null
  sudo launchctl bootstrap system "${IOGPU_PLIST}"
  sudo sysctl -w "iogpu.wired_limit_mb=${IOGPU_LIMIT_MB}" >/dev/null
}

configure_nvme_automount() {
  say "Configuring NVMe automount for ${NVME_UUID}"

  sudo mkdir -p "$(dirname "${MOUNT_SCRIPT}")"

  sudo tee "${MOUNT_SCRIPT}" >/dev/null <<EOF
#!/bin/bash
set -u

UUID="${NVME_UUID}"
EXPECTED="${NVME_MOUNT}"
LOG="${MOUNT_LOG}"
MAX_ATTEMPTS=30
SLEEP_SECONDS=2

log() {
    /bin/echo "\$(/bin/date '+%Y-%m-%d %H:%M:%S') \$*" >> "\${LOG}"
}

is_mounted() {
    /sbin/mount | /usr/bin/grep -Fq " on \${EXPECTED} "
}

# StartInterval executes this job periodically. A mounted disk is the normal
# steady state, so exit silently to avoid filling the log every 30 seconds.
if is_mounted; then
    exit 0
fi

log "NVMe not mounted; waiting for UUID \${UUID}"

attempt=1
while [ "\${attempt}" -le "\${MAX_ATTEMPTS}" ]; do
    if /usr/sbin/diskutil info "\${UUID}" >/dev/null 2>&1; then
        log "NVMe detected on attempt \${attempt}; requesting mount"
        /usr/sbin/diskutil mount "\${UUID}" >>"\${LOG}" 2>&1

        if is_mounted; then
            log "NVMe successfully mounted at \${EXPECTED}"
            exit 0
        fi

        log "Mount command completed but \${EXPECTED} is still unavailable"
    fi

    /bin/sleep "\${SLEEP_SECONDS}"
    attempt=\$((attempt + 1))
done

log "ERROR: NVMe could not be mounted after \${MAX_ATTEMPTS} attempts"
exit 1
EOF

  sudo chown root:wheel "${MOUNT_SCRIPT}"
  sudo chmod 755 "${MOUNT_SCRIPT}"

  sudo launchctl bootout system/local.mount-nvme >/dev/null 2>&1 || true

  sudo tee "${MOUNT_PLIST}" >/dev/null <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>local.mount-nvme</string>
    <key>ProgramArguments</key>
    <array>
        <string>${MOUNT_SCRIPT}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>StartInterval</key>
    <integer>30</integer>
</dict>
</plist>
EOF

  sudo chown root:wheel "${MOUNT_PLIST}"
  sudo chmod 644 "${MOUNT_PLIST}"
  sudo plutil -lint "${MOUNT_PLIST}" >/dev/null
  sudo launchctl bootstrap system "${MOUNT_PLIST}"
  sudo launchctl kickstart -k system/local.mount-nvme
}

nvme_is_mounted() {
  /sbin/mount | /usr/bin/grep -Fq " on ${NVME_MOUNT} "
}

wait_for_nvme() {
  local attempt=1

  while [[ "${attempt}" -le 40 ]]; do
    if nvme_is_mounted; then
      return 0
    fi
    sleep 2
    attempt=$((attempt + 1))
  done

  die "NVMe did not mount at ${NVME_MOUNT}. Check ${MOUNT_LOG}."
}

prepare_storage() {
  wait_for_nvme

  mkdir -p "${MODEL_DIR}"
  mkdir -p "${NVME_CACHE_DIR}"

  [[ -w "${MODEL_DIR}" ]] || die "Model directory is not writable: ${MODEL_DIR}"
  [[ -w "${NVME_CACHE_DIR}" ]] || die "NVMe cache directory is not writable: ${NVME_CACHE_DIR}"
}

start_service_for_initial_settings() {
  say "Creating initial oMLX settings"
  stop_omlx
  sudo "${BREW}" services start omlx --sudo-service-user="${USER_NAME}"

  local attempt=1
  while [[ "${attempt}" -le 30 ]]; do
    [[ -f "${SETTINGS}" ]] && break
    sleep 1
    attempt=$((attempt + 1))
  done

  [[ -f "${SETTINGS}" ]] || die "oMLX did not create ${SETTINGS}."
  sudo "${BREW}" services stop omlx
}

patch_settings() {
  [[ -f "${SETTINGS}" ]] || start_service_for_initial_settings

  backup_settings

  local py
  py="$(resolve_python)"

  export SETTINGS MODEL_DIR NVME_CACHE_DIR OMLX_HOST OMLX_PORT
  "${py}" <<'PY'
import json
import os
import secrets
from pathlib import Path

p = Path(os.environ["SETTINGS"])
data = json.loads(p.read_text())

server = data.setdefault("server", {})
requested_host = os.environ.get("OMLX_HOST", "").strip()
if requested_host:
    server["host"] = requested_host
else:
    server.setdefault("host", "127.0.0.1")
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
cache["enabled"] = True
cache["hot_cache_only"] = False
cache["ssd_cache_dir"] = os.environ["NVME_CACHE_DIR"]

hf = data.setdefault("huggingface", {})
hf["hf_cache_enabled"] = True

auth = data.setdefault("auth", {})
if not auth.get("api_key"):
    auth["api_key"] = secrets.token_urlsafe(32)
auth["skip_api_key_verification"] = False
auth["allow_unauthenticated_inference"] = False

tmp = p.with_name(p.name + ".headless-tmp")
tmp.write_text(json.dumps(data, indent=2) + "\n")
tmp.chmod(0o600)
tmp.replace(p)
PY

  chmod 600 "${SETTINGS}"
}

configure_aliases() {
  local py
  py="$(resolve_python)"

  touch "${ZSHRC}"
  export ZSHRC NVME_UUID NVME_MOUNT

  "${py}" <<'PY'
from pathlib import Path
import os
import re

p = Path(os.environ["ZSHRC"])
uuid = os.environ["NVME_UUID"]
mount = os.environ["NVME_MOUNT"]
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
    f"alias cdnvme='cd {mount}'\n"
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
}

start_omlx() {
  say "Starting oMLX as a system service running as ${USER_NAME}"
  stop_omlx
  sudo "${BREW}" services start omlx --sudo-service-user="${USER_NAME}"
}

verify_settings() {
  local py
  py="$(resolve_python)"

  export SETTINGS MODEL_DIR NVME_CACHE_DIR OMLX_PORT
  "${py}" <<'PY'
import json
import os
import sys
from pathlib import Path

p = Path(os.environ["SETTINGS"])
if not p.exists():
    print(f"Missing settings: {p}", file=sys.stderr)
    raise SystemExit(1)

data = json.loads(p.read_text())
checks = {
    "server.port": data.get("server", {}).get("port") == int(os.environ["OMLX_PORT"]),
    "model.model_dir": data.get("model", {}).get("model_dir") == os.environ["MODEL_DIR"],
    "cache.ssd_cache_dir": data.get("cache", {}).get("ssd_cache_dir") == os.environ["NVME_CACHE_DIR"],
    "auth.api_key": bool(data.get("auth", {}).get("api_key")),
    "auth.skip_api_key_verification": data.get("auth", {}).get("skip_api_key_verification") is False,
}

bad = [name for name, ok in checks.items() if not ok]
if bad:
    print("Invalid oMLX settings: " + ", ".join(bad), file=sys.stderr)
    raise SystemExit(1)

print("settings: OK")
print("server.host:", data.get("server", {}).get("host"))
print("server.port:", data.get("server", {}).get("port"))
print("model dir:", data.get("model", {}).get("model_dir"))
print("SSD cache:", data.get("cache", {}).get("ssd_cache_dir"))
print("API key configured: yes")
PY
}

verify_all() {
  say "Validating headless deployment"

  local live_limit
  live_limit="$(sysctl -n iogpu.wired_limit_mb)"
  [[ "${live_limit}" == "${IOGPU_LIMIT_MB}" ]] \
    || die "IOGPU limit is ${live_limit}, expected ${IOGPU_LIMIT_MB}."

  sudo launchctl print system/local.iogpu-wired-limit >/dev/null 2>&1 \
    || die "local.iogpu-wired-limit is not registered."

  sudo launchctl print system/local.mount-nvme >/dev/null 2>&1 \
    || die "local.mount-nvme is not registered."

  nvme_is_mounted \
    || die "NVMe is not mounted at ${NVME_MOUNT}."

  [[ -w "${NVME_CACHE_DIR}" ]] \
    || die "NVMe cache is not writable: ${NVME_CACHE_DIR}"

  verify_settings

  local attempt=1
  while [[ "${attempt}" -le 30 ]]; do
    if sudo lsof -nP -iTCP:"${OMLX_PORT}" -sTCP:LISTEN 2>/dev/null | grep -q LISTEN; then
      break
    fi
    sleep 1
    attempt=$((attempt + 1))
  done

  local listener pid process_user
  listener="$(sudo lsof -nP -iTCP:"${OMLX_PORT}" -sTCP:LISTEN 2>/dev/null || true)"
  grep -q LISTEN <<<"${listener}" || die "Nothing is listening on TCP/${OMLX_PORT}."

  pid="$(awk 'NR==2 {print $2}' <<<"${listener}")"
  [[ -n "${pid}" ]] || die "Could not determine oMLX listener PID."

  process_user="$(ps -o user= -p "${pid}" | xargs)"
  [[ "${process_user}" == "${USER_NAME}" ]] \
    || die "TCP/${OMLX_PORT} listener runs as ${process_user}, expected ${USER_NAME}."

  printf '\n%s\n' "${listener}"

  cat <<EOF

VALIDATION PASSED

User:               ${USER_NAME}
Models:             ${MODEL_DIR}
NVMe:               ${NVME_MOUNT}
SSD cache:          ${NVME_CACHE_DIR}
IOGPU wired limit:  ${live_limit} MiB
Settings:           ${SETTINGS}
oMLX version:       $("${BREW}" --prefix omlx >/dev/null 2>&1 && /opt/homebrew/opt/omlx/bin/omlx --version 2>/dev/null || echo unknown)

The API key remains in ${SETTINGS}; it is deliberately not printed.
EOF
}

mount_only() {
  [[ -f "${MOUNT_PLIST}" ]] || die "NVMe LaunchDaemon is not installed. Run: ./install.omlx-headless.sh configure"
  sudo launchctl kickstart -k system/local.mount-nvme
  wait_for_nvme
  diskutil info "${NVME_UUID}" | grep -E 'Volume Name|Mounted|Mount Point|Volume UUID'
}

configure_system() {
  check_filevault
  ensure_clt
  ensure_homebrew
  omlx_installed || die "oMLX is not installed. Run: ./install.omlx-headless.sh install"

  configure_iogpu
  configure_nvme_automount
  prepare_storage
  patch_settings
  configure_aliases
  start_omlx
  verify_all
}

case "${ACTION}" in
  install)
    check_filevault
    ensure_clt
    ensure_homebrew
    install_omlx_if_missing
    configure_system
    ;;
  configure)
    configure_system
    ;;
  update)
    check_filevault
    ensure_clt
    ensure_homebrew
    update_omlx_stable
    configure_system
    ;;
  verify)
    ensure_homebrew
    omlx_installed || die "oMLX is not installed."
    verify_all
    ;;
  mount)
    mount_only
    ;;
esac
