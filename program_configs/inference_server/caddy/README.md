<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Caddy on inference server (Mac Mini M5 Pro)

[Reading guide](../../../README.md#reading-guide) · Next: [Root CA installation](../../stacks_server/root-ca_install/README.md)

Caddy is used to TLS protect the native endpoint of oMLX that works without TLS by default.

To install Caddy it is advised to use `HomeBrew` project for simplicity. Once `brew` CLI is installed and `Caddy` is installed, the configuration is done in /opt/homebrew/etc/Caddyfile

Simply, add or modify the `Caddy` configuration file with the file in this folder.
