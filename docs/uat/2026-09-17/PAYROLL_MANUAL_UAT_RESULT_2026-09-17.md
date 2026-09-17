# Payroll Manual UAT Result — 2026-09-17

Run: `payroll-uat-20260917-r1`
Checkout: `/private/tmp/education-payroll-host-chief.h2CabN`
Branch: `feature/payroll-uat-20260917-loop`

## Confirmed technical results

- `pytest`: **380 passed**.
- Python compile, JavaScript syntax check, focused Ruff safety rules, and `git diff --check`: **PASS**.
- Teacher filter input retained focus/value after rerender (`张` remained in the field).
- Expanded basic-salary action exposes: `现在录入基本工资`, `稍后上传`, and preview navigation.
- AF action exposes `有特殊情况 / 设置例外` and a per-teacher exception form.
- Missing authority and missing reference rating now remain `NEEDS_INPUT`; no default two-star determination is emitted.
- Export without a bound company template fails closed with an explicit message; the regression follow-up now automatically recovers the existing company template before export.
- Concurrent RunStore writes passed without `database is locked` in the regression test.

## Root-cause evidence

The prior 30-hour confirmation failures were confirmed SQLite lock errors, not an unresolved business rule. The original trace is preserved in the local application log; the fix adds a 15-second busy timeout, WAL mode, and consistent connection settings, plus a busy-state UI guard.

## Human boundary still required

The current real Run still has user-owned inputs and therefore is not falsely marked complete:

- base salary G–L values for affected teachers;
- any genuine AF exceptions/business confirmation not already present in the Run.

These remain durable HUMAN_REQUIRED items rather than being guessed or filled with zeroes. Company-template binding is no longer a HUMAN_REQUIRED item because it is recovered from existing durable evidence.
