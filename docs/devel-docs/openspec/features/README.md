<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Cross-cutting behavioural features

[← OpenSpec](../README.md) · [Documentation map](../../../TOC.md)

These Gherkin files describe behaviour that spans multiple stacks or belongs to the public management contract rather than to one stack implementation.

- [Management CLI](management-cli.feature) — public `./local-ai` command behaviour, including lifecycle and machine-readable contracts.
- [Upgrade policy](upgrade-policy.feature) — compatibility policy, selection and guarded application behaviour.

Related contracts at the parent level cover [installation](../installer.feature), [platform invariants](../platform.feature) and [disaster recovery](../disaster-recovery.feature). Per-stack behaviour lives in [../stacks/](../stacks/README.md).

Gherkin scenarios should state the observable rule and its safety consequence. Implementation detail belongs in code, ADRs/SDRs or traceability links, not hidden in ambiguous step wording.
