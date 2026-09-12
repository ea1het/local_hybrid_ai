# SDR-0005 — Explicit Open WebUI model access

Status: accepted

## Risk

Disabling model access control globally would expose every upstream model to ordinary users and make future provider/model additions visible without review.

## Decision

`BYPASS_MODEL_ACCESS_CONTROL` remains disabled. Stack7 explicitly reconciles `basic_autorouter`, grants the Open WebUI wildcard user principal (`user:*`) read access only to that model, and keeps administrator access separate.

## Verification

A regular-user qualification must show only `basic_autorouter`; the model must have exactly the intended public read grant. Coverage lives in Stack7 contract tests and the recorded qualification evidence under `docs/dr/status.md` and `docs/pending.md`.
