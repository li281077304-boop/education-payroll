# Payroll Current State — 2026-09-17

## Source provenance

- Task source: `/Users/macos/Downloads/TASK_2026-09-17_PAYROLL_LOOP.md`
- Manual UAT source: `/Users/macos/Downloads/UAT_2026-09-17_MANUAL_PAYROLL.md`
- Task SHA-256: `f1a3267a4eabb337706ed34b8473d62287b78686f3e7071842a7f5fc5e55f452`
- Manual UAT SHA-256: `1e648a0ab6670e9d7a6bd1793eb55eb8e75f5a03bf796ed31adbe3444c262d3f`

## Repository

- Canonical local checkout: `/private/tmp/education-payroll-host-chief.h2CabN`
- Branch at run start: `feature/payroll-uat-20260917-loop`
- Starting HEAD: `ec1fe201077aa6f41e2aa2a3dd62f63ef875ec49`
- Existing untracked `.ralph` runtime evidence is preserved and not cleaned.

## Product baseline

- Offline/local-first Payroll core and UI.
- July/August rule reconstruction is existing evidence and must remain period-isolated.
- Existing historical UAT evidence reports 17 obligations with 11 PASS, 6 HUMAN_BLOCKED, 0 TECHNICAL_OPEN, and 0 FAILED for the prior August run.

## This run

- Run id: `payroll-uat-20260917-r1`
- Objective: close the real manual Payroll UAT path without inventing business rules.
- Initial phase: DURABLE_PERSISTENCE
- Human Interrupt Count target: 0
- Raw payroll files remain read-only; outputs must be new artifacts.

## Confirmed UAT scope

P0: teacher filter focus loss; missing-star semantics; company-template export; 30-hour confirmation; base-salary workflow; explicit issue expansion and special-case paths.

P1: preview usability, three-color status, scrolling, and concise evidence presentation.

## Unknowns requiring evidence, not guesses

- Exact source and runtime behavior of the 30-hour failure code `4ac7c59609da3256`.
- Company payroll template path/binding for export.
- Whether any missing business facts remain genuinely user-only after deterministic processing.

## Verification update

- Full regression: 378 passed.
- The 30-hour failure was confirmed as SQLite lock contention and remediated
  with busy-timeout/WAL connections plus duplicate-submit protection.
- Local UI replay verified filter focus/value retention and explicit base-salary
  action controls.
- Base-salary inputs and company-template binding remain user-owned blockers;
  no values are guessed and no incomplete run is marked PASS.
