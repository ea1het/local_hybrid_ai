<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Root CA installation

[Reading guide](../../../README.md#reading-guide) · Next: [Stack 00 · Platform](../../../stack-00_-_platform/README.md)

The CA is created with mkcert on the inference server (Mac mini), see [../../inference_server/mkcert/README.md](../../inference_server/mkcert/README.md).

The stacks server domains are configurable through environment variables in its central `.env`; `casa.lan` and `*.casa.lan` are defaults, not fixed names. Set the domain with `ROOT_HOSTNAME`, and set the service subdomains with `SEARCH_HOSTNAME`, `CHAT_HOSTNAME`, `GIT_HOSTNAME`, `GWIA_HOSTNAME`, `HOMELAB_HOSTNAME`, and `NORAI_HOSTNAME` (see [`.env.template`](../../../.env.template)). Set `TLS_SAN_DOMAINS` to the DNS names the issued server certificate must cover, and pass those same names to mkcert when issuing it. The inference server's `mlx.casa.lan` example is configured separately in its Caddyfile. Distributing `rootCA.pem` establishes trust in the CA; it does not change the certificate's DNS names.

| File | Role | Distributed to clients |
| --- | --- | --- |
| `rootCA.pem` | CA certificate (public) | **Yes** — this guide |
| `rootCA-key.pem` | CA private key | **Never** |
| `tls.crt` / `tls.key` | Server certificate and key for the names in `TLS_SAN_DOMAINS` (default `casa.lan` / `*.casa.lan`) | **No** — only to servers that terminate TLS (Caddy, Stack 00/HAProxy); see the mkcert guide |

## 1. Distribute the CA to other machines

Clients only need the **public** `rootCA.pem`. **Never** copy `rootCA-key.pem`, and do not install `tls.crt` as a trusted root: clients trust the CA, not the server certificate.

Copy it out of the Mac mini, e.g.:

```sh
cp "$(mkcert -CAROOT)/rootCA.pem" /Users/norai/Documents/MKCert/rootCA.pem
```

After installing on each client, compare the SHA-256 fingerprint with the one from [step 3.3 of the mkcert guide](../../inference_server/mkcert/README.md#33-inspect-the-ca).

### 1.1 Linux stacks server (Stack 00)

Copy the CA to `LOCAL_CA_SOURCE_PATH` in the root `.env` (default `/tmp/rootCA.pem`), where [stack-00_-_platform/install-ca-cert.py](../../../stack-00_-_platform/install-ca-cert.py) expects it:

```sh
scp /Users/norai/Documents/MKCert/rootCA.pem <user>@<docker-host>:/tmp/rootCA.pem
```

`./local-ai stack-00 install` runs it for you. To run it on its own:

```sh
cd /opt/docker/stacks/stack-00_-_platform
sudo ./install-ca-cert.py
```

(Or pass the CA explicitly: `sudo ./install-ca-cert.py --ca /path/to/rootCA.pem`.) A valid, trusted CA that is already installed is kept; use `--force` to replace it (for example to rotate the CA).

It validates the CA, installs it as `/usr/local/share/ca-certificates/${LOCAL_CA_NAME}.crt` (`LOCAL_CA_NAME` from the central `.env`, default `casa-local-ca`), runs `update-ca-certificates`, checks the host bundle and stops. Set `LOCAL_CA_SOURCE_PATH` to an absolute path such as `/opt/temporal/rootCA.pem` if the source is not in `/tmp`. It does not modify any stack: LiteLLM (Stack 30) already mounts the host bundle `/etc/ssl/certs/ca-certificates.crt` and sets `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` in its own Compose file. If LiteLLM is already running, restart it to pick up the updated bundle.

The certificate HAProxy **serves** (`tls.crt` / `tls.key`) is installed separately by `install-tls-certs.py`, see [section 6 of the mkcert guide](../../inference_server/mkcert/README.md#6-use-the-certificate-on-the-stacks-server-stack-00).

Manual equivalent on Debian/Ubuntu (without the script):

```sh
sudo cp rootCA.pem /usr/local/share/ca-certificates/casa-local-ca.crt
sudo update-ca-certificates
```

On Fedora/RHEL:

```sh
sudo cp rootCA.pem /etc/pki/ca-trust/source/anchors/casa-local-ca.pem
sudo update-ca-trust
```

### 1.2 Other macOS workstations

```sh
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain rootCA.pem
```

(Or double-click `rootCA.pem`, add it to the **System** keychain and set "When using this certificate" to **Always Trust**.)

Alternatively, if mkcert is installed on the workstation, point it at a directory that contains **only** `rootCA.pem`:

```sh
mkdir -p ~/casa-ca && cp rootCA.pem ~/casa-ca/
CAROOT=~/casa-ca mkcert -install
```

### 1.3 Windows

From an elevated PowerShell:

```powershell
Import-Certificate -FilePath .\rootCA.pem -CertStoreLocation Cert:\LocalMachine\Root
```

### 1.4 iOS / iPadOS

1. AirDrop or email `rootCA.pem` to the device and install the profile (Settings → Profile Downloaded → Install).
2. Enable full trust: Settings → General → About → Certificate Trust Settings → enable the mkcert CA.

### 1.5 Runtimes that ignore the OS trust store

Some tools ship their own CA bundle and need to be told about the CA explicitly:

| Runtime | Setting |
| --- | --- |
| Node.js (e.g. opencode, npm) | `export NODE_EXTRA_CA_CERTS=/path/to/rootCA.pem` |
| Python `requests` / `httpx` (certifi) | `export REQUESTS_CA_BUNDLE=/path/to/bundle.pem` and/or `SSL_CERT_FILE=/path/to/bundle.pem` |
| Python.org installer on macOS | run `/Applications/Python 3.x/Install Certificates.command`, then set the variables above |
| `curl` with a custom CA | `curl --cacert /path/to/rootCA.pem https://mlx.casa.lan` |
| Firefox | installed automatically by `mkcert -install` if `nss` is present; otherwise Settings → Privacy & Security → Certificates → Import |
| Docker containers | mount the host bundle and set `SSL_CERT_FILE` (what Stack 30's Compose file does) |

For Python, `bundle.pem` should be the system bundle **plus** the CA (e.g. `/etc/ssl/certs/ca-certificates.crt` on Debian after `update-ca-certificates`), otherwise public HTTPS sites stop validating.
