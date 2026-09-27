# Fifth Round UAT — Roster, Group Confirmation, Renewal Classification, Launcher

Date: 2026-09-27
Run: `7f2f44465a86` (2026-08)
Scope: schedule-authoritative roster; subject-group preview/confirmation; renewal classification; macOS launcher. Part-time, AG, AL, AS, AV, and annotation logic were not changed.

## Results

| Area | Result | Evidence |
|---|---|---|
| Schedule-authoritative roster | PASS | 2,385 in-period schedule rows; 51 unique schedule teachers; roster 51; schedule-only 0; roster-only 0. Period 2026-08-03–2026-08-30. |
| Optional teacher IDs | PASS | Schedule adapters preserve teacher IDs when present. Same normalized name with distinct IDs fails closed. |
| Subject-group confirmation gate | PASS | Direct service import is rejected; direct HTTP `/files` is rejected with 409. Preview leaves current salary/core/roster untouched. Confirmation records actor, time, period, hash, sheet and counts. Replacement requires explicit confirmation and retains prior history. |
| Subject-group browser UAT | PASS (isolated copy) | Real 2026-08 Run and source files were cloned to an isolated SQLite database. Browser preview showed 30 source teachers, 30 roster matches and 3 possible group omissions. Confirmed with a test actor; after browser reload and reopening the same Run, UI still showed “已确认用于本月工资”. No production business approval was written. |
| Renewal classification | PASS | MATCHED 45; NO_RENEWAL_ROW 6; IDENTITY_UNMATCHED 0; OUTSIDE_ROSTER 4. The prior two “unmatched” entries classify as NO_RENEWAL_ROW, not identity failure. |
| Installed app UAT A: service stopped | PASS | Finder double-click of the installed app started service on port 8760, passed health, and opened the default browser. The existing 2026-08 Run was visible. |
| Installed app UAT B: service running | PASS | Second Finder double-click reused the same PID; launcher log recorded `reused`; no second service appeared. |
| Installed app UAT C: restart | PASS | Finder double-click of the restart app safely stopped its recorded PID, started a new PID on port 8760, passed health, and opened the browser. |
| Invalid repo/Python configuration | PARTIAL | A copied test bundle produced `REPO_PATH_INVALID` and `PYTHON_PATH_INVALID` durable diagnostics through the bundled bootstrap. `osascript` was launched for each Chinese dialog, but the dialog itself was not visually captured by the available UI surface. |
| Recovery after invalid configuration | PASS | The installed production app remained usable after the isolated bad-config tests and reused the healthy service. |
| Production data safety | PASS | App before/after checks used `/Users/macos/Library/Application Support/EducationPayroll`. The same SQLite file remained readable, `integrity_check=ok`, 9 Runs remained, and Run `7f2f44465a86` remained present. Its SHA256 did not change during this task. |

## Launcher root-cause evidence

Before reinstall, the two installed bundles were dated 2026-09-24 and lacked `Contents/Resources/bootstrap.sh`. Their launcher scripts embedded the checkout and `.venv` paths, then executed `cd "$REPO_ROOT" || exit 1` before Python could write diagnostics or show an error. This proves a silent-exit design defect. At inspection time both embedded paths still existed and were executable, and prior launcher logs showed successful starts/reuses. Therefore the exact historical click that produced no visible response cannot be tied to a specific missing path from existing logs.

The new bundle starts through an app-relative bootstrap that validates configuration before calling Python and records a user-readable failure. The business code and interpreter still reside in the local checkout/venv; this change improves failure visibility but does not make the app independent of the development repository.

## Regression

- Focused fifth-round and affected regression tests: 192 passed before the full suite.
- Full required suite: `sh tools/run_tests.sh` — 583 passed.
- Launcher shell syntax check: PASS.
- `git diff --check`: PASS.

The active production Run remains unconfirmed for its legacy math group file. This is deliberate: the confirmation click was exercised only against an isolated copy and must not be treated as the payroll owner's approval.
