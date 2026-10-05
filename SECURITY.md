<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Security Policy

## Supported Versions

Use this section to tell people about which versions of your project are
currently being supported with security updates.

| Version | Supported          |
| ------- | ------------------ |
| 0.8.1   | :white_check_mark: |
| 0.8.0   | :white_check_mark: |
| < 0.8.0 | :x:                |


## Reporting a Vulnerability

Security must be taken seriously. If you discover a vulnerability, please report it using a **private GitHub issue**.

### How to Report

1. Go to the repository on GitHub.
2. Create a **new private issue** (label it `security`).
3. Include the following information:
   - A clear description of the vulnerability.
   - Steps to reproduce the issue (POC / PoC code, screenshots, or logs).
   - The affected version(s) of **Local Hybrid AI**.
   - Your contact information (optional, for follow-up).

> [!CAUTION]
> **Do not** open a public issue or discuss the vulnerability publicly until it has been responsibly disclosed and a fix is available.

### What to Expect
| Stage | Timeline |
|-------|----------|
| **Acknowledgement** | Acknowledge receipt will be issued within **48 hours** for critical vulnerabilities, and up to **1 week** for medium/low severity. |
| **Assessment** | Assessment over the vulnerability will be carried out to determine its impact within **1–2 weeks**. |
| **Fix / Mitigation** | The aim is to release a patch or mitigation within **2–4 weeks** for critical issues, and **1–2 months** for medium/low severity (subject to complexity). |
| **Public Disclosure** | Once a fix is released, there will be coordination with you on the timing of public disclosure. |

If the vulnerability is **accepted**, it's expected to work with you to develop a fix and credit you appropriately (unless you prefer anonymity).
If **declined**, it will be provided a clear explanation in a brief, private response.


## Responsible Disclosure Policy

To follow a responsible disclosure approach:

- **Good faith**: Researchers and users who report vulnerabilities in good faith will not face legal action for doing so.
- **Coordination**: Work with reporters to validate, fix, and coordinate disclosure timelines.
- **Credit**: Gladly credit reporters who follow this policy (unless anonymity is requested).
- **Testing boundaries**: Do not test vulnerabilities on production environments without explicit written consent.


## Dependency Security

**[Dependabot](https://github.blog/2020-06-01-keep-all-your-packages-up-to-date-with-dependabot/)** is in use to automatically monitor and update dependencies for known vulnerabilities.

- Dependabot opens pull requests for outdated or vulnerable dependencies.
- A review and merge of these PRs happens on a regular schedule.
- Users are encouraged to **keep their installations up to date** with the latest supported version of **Local Hybrid AI**.

> [!TIP]
> Enable Dependabot alerts in your own fork or integration by ensuring the `.github/dependabot.yml` file is present and configured.
