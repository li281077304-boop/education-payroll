# Payroll branch integration audit

Audit scope: the integration line based on `integration/payroll-v1-final-20260929` at `6f02ce7031c2ede75a93531e2e2cfcc7633e88eb`, before this recovery patch is committed. “MERGED” below means the useful change is present in this integration line, either as an ancestor or an audited equivalent patch; it does not mean this integration line has been merged into `main`.

## Branch disposition

| Branch | Status | Basis |
|---|---|---|
| `main` | MERGED | Its current tip is an ancestor of the integration base. This audit does not update `main`. |
| `feature/payroll-manual-uat-20260926` | MERGED | Integration base contains its current published line and follow-up Windows launcher/release identity commits. |
| `feature/payroll-core-v1` | MERGED | Ancestor of the integration base. |
| `feature/payroll-excel-adapter` | MERGED | Ancestor of the integration base. |
| `feature/payroll-ui-v1` | MERGED | Ancestor of the integration base. |
| `feature/payroll-aa-ac-audit` | MERGED | Published feature ref is an ancestor of the integration base. |
| `feature/payroll-business-inputs-writeback` | MERGED | Published feature ref is an ancestor of the integration base. |
| `feature/payroll-dual-mode-class-rules` | MERGED | Published feature ref is an ancestor of the integration base. |
| `feature/payroll-reliability-audit` | MERGED | Published feature ref is an ancestor of the integration base. |
| `feature/payroll-resolution-workflows` | MERGED | Published feature ref is an ancestor of the integration base. |
| `feature/payroll-semantic-import` | MERGED | Published feature ref is an ancestor of the integration base. |
| `feature/payroll-standard-submission` | MERGED | Published feature ref is an ancestor of the integration base. |
| `integration/payroll-20260921` | MERGED | Ancestor of the integration base; includes the audited anti-copy and manual-adjustment semantics. |
| `integration/payroll-v1` | MERGED | Published ref is an ancestor of the integration base. |
| `night/payroll-continuation-01` | MERGED | Ancestor of the integration base. |
| `nightshift/data-layer-20260912` | MERGED | Ancestor of the integration base. |
| `ralph/ad-aa-ac` | MERGED | Ancestor of the integration base. |
| `integration/uat-20260913` | MERGED | Its three non-ancestor commits were checked as patch-equivalent to changes already in the integration history. |
| `codex/payroll-p0-exempt-fix` | MERGED | Its unique commit is patch-equivalent to the integrated exemption fix. |
| `ralph/ad-aa-ac-dde` | MERGED | `2dccd63` anti-copy and `3954d9a` manual-adjustment behavior are represented by later semantic integration commits in the base; no wholesale branch merge is needed. |
| `feature/payroll-windows-compat` | SUPERSEDED | Its three unique commits are the earlier Windows RC1 path. The maintained launcher/build line is in the integration base; do not restore the old PyInstaller/launcher implementation. |
| `feature/payroll-real-e2e` | SUPERSEDED | Its unique file-read/logging patch is replaced by current source-copy validation, actionable error responses, and technical diagnostics. |
| `feature/payroll-core-config-chain` | SUPERSEDED | Its unique shell change belongs to the earlier Windows wrapper and is replaced by the current launcher. |
| `feature/payroll-peripheral-authorities` | SUPERSEDED | Its two unique peripheral-authority commits predate the current submission-first input chain and are not part of this recovery scope. |
| `feature/payroll-uat-20260917-loop` | SUPERSEDED | Its ten unique commits are earlier UAT/UI iterations or temporary evidence, replaced by later monthly-close flows and current tests. |
| `night/hy4-uat-20260912` | SUPERSEDED | Four unique commits are older handoff/UAT iterations superseded by later product and test history. |
| `night/hy4-uat2-20260912` | SUPERSEDED | Eight unique commits are older handoff/UAT iterations superseded by later product and test history. |
| `night/longrun-20260913` | SUPERSEDED | Its four unique commits include an older rule line that conflicts with later confirmed class-type behavior; do not merge it. |
| `ralph/finite-worker-real-payroll-20260915` | SUPERSEDED | Its unique commit is temporary worker/UAT evidence, not a missing product change. |

## Important unique changes audited

- `2dccd63de6a5d81afabbf4a8613b8d9bf9ce1242` — anti-copy/current-run rendering. Preserved by the later workbook anti-copy integration and its regression tests.
- `3954d9aeb5d3a2035a6cb39afbaa1ff1fad27b42` — manual-adjustment lifecycle. Preserved by the later manual-adjustment integration and its regression tests.
- `03f94602c06e51fc244b851ca671ad68daeb59d8` and `6f02ce7031c2ede75a93531e2e2cfcc7633e88eb` — Windows launcher and release evidence. Both are in the selected `6f02ce7` integration base.
- The other non-ancestor refs above were inspected for their unique commits; none contains an additional current, validated fix that should be merged wholesale into this recovery patch.

## Integration boundary

This patch remains on `integration/payroll-v1-final-20260929`. It does not merge into or modify `main`; the only remote write requested for this round is a normal push of this integration branch after review and safety checks.
