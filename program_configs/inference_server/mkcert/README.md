<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# MKCert (CA)

[Reading guide](../../../README.md#reading-guide) · Next: [Caddy](../caddy/README.md)

The `mkcert` package is used to create a self-signed CA (certificate authority) for the certificates to be used in the local domain `*.casa.lan`, as an example. You can configure any other.

Later, it is necessary to distribute the certificates with the CA certificate for complete certificate path validation in local machines, workstations and similar devices like tablets and mobile devices.

This guide covers the full setup on the inference server of this project, a **Mac mini M5 Pro**, Apple Silicon, macOS, provisioned with a local user account named `norai`):

1. Install the prerequisites (Xcode Command Line Tools, Homebrew).
2. Install `mkcert` (and `nss` for Firefox support).
3. Create the local CA and trust it on the Mac mini.
4. Issue a wildcard certificate for `casa.lan` / `*.casa.lan`.
5. Wire the certificate (`tls.crt` / `tls.key`) into Caddy.
6. Install the CA and the same certificate (`tls.crt` / `tls.key`) on the stacks server with Stack 00 (for HAProxy).
7. Verify, renew and (if needed) revoke/rotate.

Distributing the CA certificate (`rootCA.pem`) to clients is covered in [../../stacks_server/root-ca_install/README.md](../../stacks_server/root-ca_install/README.md).

File naming used across the project:

- **CA**: `rootCA.pem` (public, distributed to clients) and `rootCA-key.pem` (private, never leaves the Mac mini).
- **Wildcard server certificate**: `tls.crt` (certificate) and `tls.key` (private key). These are the names Caddy is configured with and the names Stack 00 installs for HAProxy (`${BASE_PATH}/service_-_haproxy/config/{tls.crt,tls.key}`).

---

## Conventions used in this guide

| Item | Value |
| --- | --- |
| Host | Mac mini M5 Pro (Apple Silicon, `arm64`) |
| macOS user | `norai` |
| Homebrew prefix | `/opt/homebrew` |
| mkcert CA directory (`CAROOT`) | `~/Library/Application Support/mkcert` |
| Certificate output directory | `/Users/norai/Documents/MKCert` |
| CA certificate (public, distributed) | `rootCA.pem` |
| CA private key (never leaves the Mac mini) | `rootCA-key.pem` |
| Wildcard server certificate | `tls.crt` |
| Wildcard server private key | `tls.key` |
| Names covered | `casa.lan`, `*.casa.lan` |

The certificate paths match the ones referenced in [../caddy/Caddyfile](../caddy/Caddyfile). If you change them, update the `Caddyfile` too. Keep the file names `tls.crt` / `tls.key`: they are also the names expected by Stack 00 (section 6).

> **Important:** all commands are run **as the user `norai`**, not with `sudo`, unless explicitly stated. `mkcert` stores the CA in the invoking user's home directory; running it with `sudo` would create a different CA under root's home.

---

## 1. Prerequisites

### 1.1 Local session (not only SSH)

Step 3 (`mkcert -install`) adds the CA to the macOS **System keychain** and changes its trust settings. macOS requires an interactive authorization for that, which is **not possible over a plain SSH session**. In that scenario it's being received an error like `SecTrustSettingsSetTrustSettings: The authorization was denied since no user interaction was possible`).

Run at least step 3 from:

- the Mac mini's own screen/keyboard, or
- **Screen Sharing** (System Settings → General → Sharing → Screen Sharing), opening Terminal.app inside the remote desktop.

All other steps can be done over SSH.

### 1.2 Xcode Command Line Tools

Homebrew needs them:

```sh
xcode-select --install
```

A dialog appears; accept and wait for it to finish. Verify:

```sh
xcode-select -p
# /Library/Developer/CommandLineTools
```

### 1.3 Homebrew

If `brew` is not yet installed:

```sh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

On Apple Silicon Homebrew installs into `/opt/homebrew`. Add it to the shell environment (zsh is the macOS default):

```sh
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"
```

Verify:

```sh
brew --version
brew doctor
```

---

## 2. Install mkcert

```sh
brew update
brew install mkcert
```

Optional but recommended is to install `nss` so mkcert can also register the CA in **Firefox** profiles (Firefox uses its own trust store, not the macOS keychain):

```sh
brew install nss
```

Verify:

```sh
which mkcert
# /opt/homebrew/bin/mkcert
mkcert -version
```

---

## 3. Create the local CA and trust it on the Mac mini

### 3.1 Create and install the CA

From a **local or Screen Sharing** Terminal session (see 1.1):

```sh
mkcert -install
```

What happens:

1. On the first run mkcert generates a new CA (RSA 3072, valid 10 years) in `CAROOT`:
   - `rootCA.pem` — the **public** CA certificate (this is what is going to be distributed later).
   - `rootCA-key.pem` — the CA **private key** (this must never leave the Mac mini).
2. It adds `rootCA.pem` to the macOS **System keychain** as a trusted root. macOS will ask for the account login/password.
3. If `nss` is installed and Firefox has a profile, it also installs the CA into Firefox.

Expected output (similar to):

```text
Created a new local CA 💥
Sudo password:
The local CA is now installed in the system trust store! ⚡️
The local CA is now installed in the Firefox trust store (requires browser restart)! 🦊
```

### 3.2 Locate the CA files

```sh
mkcert -CAROOT
# /Users/norai/Library/Application Support/mkcert

ls -l "$(mkcert -CAROOT)"
# rootCA-key.pem
# rootCA.pem
```

### 3.3 Inspect the CA

```sh
openssl x509 -in "$(mkcert -CAROOT)/rootCA.pem" -noout -subject -issuer -dates -fingerprint -sha256
```

Write down the SHA-256 fingerprint: it is useful to verify later that the same CA was installed on the other machines.

Check it is present and trusted in the System keychain:

```sh
security find-certificate -c "mkcert" -a -Z /Library/Keychains/System.keychain | grep -E "SHA-256|alis"
```

Alternatively, open **Keychain Access → System → Certificates** and look for `mkcert norai@<hostname>`; it must show "This certificate is marked as trusted for all users".

### 3.4 Protect the CA private key

Anyone holding `rootCA-key.pem` can issue certificates that every machine trusting this CA will accept (for **any** domain, not only `casa.lan`). Therefore:

```sh
chmod 600 "$(mkcert -CAROOT)/rootCA-key.pem"
```

- Never copy it into this repository, a Docker image, a shared folder or another host.
- Back it up offline (for example an encrypted USB drive or a password manager attachment). If it is lost it wont be possible again to issue new certificates with the same CA and must redistribute a new CA to every client.

---

## 4. Issue the wildcard certificate for `casa.lan`

### 4.1 Create the output directory

```sh
mkdir -p /Users/norai/Documents/MKCert
cd /Users/norai/Documents/MKCert
```

### 4.2 Generate the certificate

```sh
mkcert \
  -cert-file tls.crt \
  -key-file  tls.key \
  "casa.lan" "*.casa.lan"
```

Output files (in `/Users/norai/Documents/MKCert`):

| File | Content |
| --- | --- |
| `tls.crt` | Wildcard **server** certificate for `casa.lan` / `*.casa.lan` (PEM) |
| `tls.key` | Private key of the server certificate (PEM) |

`-cert-file` and `-key-file` are required to get these names; without them mkcert would write `casa.lan+1.pem` and `casa.lan+1-key.pem`. The CA files keep their mkcert names (`rootCA.pem`, `rootCA-key.pem`) in `CAROOT`.

Notes:

- `*.casa.lan` covers **one** label level only: `mlx.casa.lan`, `litellm.casa.lan`, … It does **not** cover the apex `casa.lan` (hence it is listed explicitly) nor deeper names like `a.b.casa.lan`. For  deeper names, add them explicitly (e.g. `"*.svc.casa.lan"`).
- It is also possible to add IPs or short hostnames to the same certificate if needed, e.g. `localhost 127.0.0.1 ::1`. Preference is to avoid this option.
- Always quote `"*.casa.lan"` so `zsh` does not try to expand the `*`.
- The names passed to mkcert must include every name listed in `TLS_SAN_DOMAINS` in the stacks server `.env` (default `"casa.lan *.casa.lan"`); Stack 00 `install-tls-certs.py` refuses a certificate that misses any of them.
- The leaf certificate is valid for **2 years and 3 months** (below Apple's 825-day limit for trusted TLS certificates). Note the expiry date to renew it in time (section 7). This certificae lifespan is forced by this situation.

Expected output (similar to):

```text
Created a new certificate valid for the following names 📜
 - "casa.lan"
 - "*.casa.lan"

Reminder: X.509 wildcards only go one level deep, so this won't match a.b.casa.lan ℹ️

The certificate is at "tls.crt" and the key at "tls.key" ✅

It will expire on <date> 🗓
```

### 4.3 Set permissions

```sh
chmod 644 tls.crt
chmod 600 tls.key
```

The key must be readable by the user that runs Caddy. If Caddy runs as `norai` (`brew services start caddy`), `600` owned by `norai` is correct. If it was run as root (`sudo brew services start caddy`), root can read it anyway.

### 4.4 Verify the certificate

Subject Alternative Names and validity:

```sh
openssl x509 -in tls.crt -noout -subject -issuer -dates -ext subjectAltName
```

It must list `DNS:casa.lan, DNS:*.casa.lan`.

Chain against the CA:

```sh
openssl verify -CAfile "$(mkcert -CAROOT)/rootCA.pem" tls.crt
# tls.crt: OK
```

Key matches the certificate (both hashes must be identical):

```sh
openssl x509 -in tls.crt -noout -pubkey | openssl sha256
openssl pkey -in tls.key -pubout | openssl sha256
```

### 4.5 (Optional) Full-chain file

`mkcert` writes only the leaf certificate. Most clients already trust the CA, so this is enough. If some client needs the server to present the full chain, create a bundle and point the server to it instead:

```sh
cat tls.crt "$(mkcert -CAROOT)/rootCA.pem" > tls-fullchain.crt
```

---

## 5. Use the certificate in Caddy

The Caddy config in [../caddy/Caddyfile](../caddy/Caddyfile) already points to the files generated above:

```caddyfile
mlx.casa.lan {
    tls /Users/norai/Documents/MKCert/tls.crt /Users/norai/Documents/MKCert/tls.key
    reverse_proxy 127.0.0.1:8000
}
```

Copy it to `/opt/homebrew/etc/Caddyfile` (see [../caddy/README.md](../caddy/README.md)), then validate and reload:

```sh
caddy validate --config /opt/homebrew/etc/Caddyfile
brew services restart caddy
```

Any additional `*.casa.lan` site block can reuse the same `tls` line.

> WARNING:  
> Name resolution for `*.casa.lan` (local DNS server, router, or `/etc/hosts`) is outside the scope of this guide, but it must resolve `mlx.casa.lan` to the Mac mini's LAN IP on every client.

---

## 6. Use the certificate on the stacks server (Stack 00)

HAProxy (Stack 10) serves the same wildcard certificate. Stack 00 installs it, together with the CA.

### 6.1 Copy the files to the stacks server

From the Mac mini:

```sh
cd /Users/norai/Documents/MKCert
cp "$(mkcert -CAROOT)/rootCA.pem" .
scp rootCA.pem tls.crt tls.key <user>@<docker-host>:/tmp
```

The destination must match `LOCAL_CA_SOURCE_PATH`, `TLS_CERT_SOURCE_PATH`, and `TLS_KEY_SOURCE_PATH` in the server's `.env` (default `/tmp/...`).

### 6.2 Install with Stack 00

On the stacks server, from the repository root:

```sh
sudo ./local-ai stack-00 install
```

`install-ca-cert.py` adds the CA to the host trust store. `install-tls-certs.py` checks the pair (matching key, signed by the CA, every name in `TLS_SAN_DOMAINS`, not expired) and installs it as `${BASE_PATH}/service_-_haproxy/config/tls.crt` (`0644`) and `tls.key` (`0640`, `root:local-hybrid-pki`). See the [Stack 00 README](../../../stack-00_-_platform/README.md).

The scripts never delete the source files. Remove the private key copy when you are done:

```sh
rm -f /tmp/tls.key
```

If HAProxy is already running, restart it to load the pair: `cd stack-10_-_haproxy_web && sudo docker compose restart haproxy`.

---

## 7. Verify, renew, rotate

### 7.1 End-to-end check

From any client that trusts the CA:

```sh
curl -v https://mlx.casa.lan/v1/models
```

The TLS handshake must succeed without `-k`. An HTTP `401`/`403` is fine: it proves DNS + TLS + CA + Caddy work.

Inspect what the server actually presents:

```sh
openssl s_client -connect mlx.casa.lan:443 -servername mlx.casa.lan </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates -ext subjectAltName
```

### 7.2 Check expiry

```sh
openssl x509 -in /Users/norai/Documents/MKCert/tls.crt -noout -enddate
# Returns non-zero if it expires within the next 30 days:
openssl x509 -in /Users/norai/Documents/MKCert/tls.crt -noout -checkend $((30*24*3600))
```

### 7.3 Renew the wildcard certificate

Before it expires, on the Mac mini (this overwrites `tls.crt` and `tls.key`):

```sh
cd /Users/norai/Documents/MKCert
mkcert -cert-file tls.crt -key-file tls.key "casa.lan" "*.casa.lan"
chmod 600 tls.key
brew services restart caddy
```

Then copy the new `tls.crt` / `tls.key` to the stacks server, run `sudo ./install-tls-certs.py --renew` in `stack-00_-_platform` (without `--renew` a still-valid installed pair is kept), and restart HAProxy (section 6). If you add names to the certificate, add them to `TLS_SAN_DOMAINS` in `.env` as well.

Because the same CA signs it, **clients need no changes**.

### 7.4 Rotate the CA (compromise or loss of `rootCA-key.pem`)

mkcert has no revocation (no CRL/OCSP). If the CA key is compromised, the only remedy is to replace the CA:

```sh
mkcert -uninstall                          # remove old CA from the Mac mini trust stores
rm -rf "$(mkcert -CAROOT)"                 # delete old CA files
mkcert -install                            # create and trust a new CA
# then repeat sections 4-6 (new tls.crt / tls.key for Caddy and Stack 00;
# use install-ca-cert.py --force), redistribute the new rootCA.pem
# and remove the old CA from each client's trust store.
```

---

## Quick reference

```sh
# Install
brew install mkcert nss
mkcert -install                            # local/Screen Sharing session only

# Issue wildcard
mkdir -p ~/Documents/MKCert && cd ~/Documents/MKCert
mkcert -cert-file tls.crt -key-file tls.key "casa.lan" "*.casa.lan"
chmod 600 tls.key

# Verify
openssl verify -CAfile "$(mkcert -CAROOT)/rootCA.pem" tls.crt
openssl x509 -in tls.crt -noout -dates -ext subjectAltName

# Stacks server (files copied to the paths set in .env)
sudo ./local-ai stack-00 install                            # first install
cd stack-00_-_platform && sudo ./install-tls-certs.py --renew   # renewal

# CA to distribute (public only)
echo "$(mkcert -CAROOT)/rootCA.pem"
```
