# Payroll Branch Integration Plan

## Scope

This integration branch is based on `4817b41ab9e5f273fb76b58e4d787e36fd8c0b3f` and is intended to combine the latest material-intake/UI flow with the already-frozen final-workbook anti-copy and manual-adjustment semantics.

No new payroll business rules, peripheral modules, Windows work, or `main` integration are in scope.

## Common ancestor and branch topology

- Integration source: `4817b41` (`night/longrun-20260913`)
- Anti-copy/manual-adjustment line: `ralph/ad-aa-ac-dde`
- Common ancestor: `4ccebdadefb7a256a060c5b99aef29b69e9a59e4`
- Missing commits after the common ancestor:
  - `2dccd63de6a5d81afabbf4a8613b8d9bf9ce1242` — final-workbook anti-copy contract and implementation
  - `3954d9aeb5d3a2035a6cb39afbaa1ff1fad27b42` — production manual-adjustment path and regression evidence

`ralph/ad-aa-ac-dde` contains only these two commits after the common ancestor. The integration must not merge the whole branch as a replacement for the current line: the current line contains newer material intake, grade/history, UAT, and service changes that are not present on the Ralph line.

## Required commits

Both missing commits are required, but their semantics must be ported into the current files:

1. `2dccd63`: anti-copy final workbook generation, current-run/source-driven final columns, empty-template behavior, cache/comment hygiene, and associated model/contract tests.
2. `3954d9a`: manual-adjustment statuses, production service creation path, persistence/reopen/revoke behavior, and associated regression evidence.

The UAT markdown/JSON files from those commits are evidence only; they must be checked for sensitive content before any commit. Real local screenshots are not part of this integration.

## Overlapping files and expected conflicts

Expected semantic overlap:

- `payroll_core/excel/package.py`: both lines have materially different package/import logic. Preserve the current package/material-flow implementation and port only anti-copy helpers that are actually needed.
- `payroll_core/excel/standard_payroll_render.py`: current renderer has newer material/run behavior; port anti-copy and adjustment semantics without replacing the current renderer wholesale.
- `payroll_ui/service.py`: both lines modify a high-churn service. Preserve current material intake, run recovery, grade inference, resolution, and issue workflows while adding only the manual-adjustment/final-workbook integration points.
- `payroll_core/models/__init__.py`: add exported model symbols without removing current models.
- `payroll_ui/business_inputs.py`: add manual-adjustment lifecycle compatibility while retaining current input/version/run binding behavior.
- `tests/test_final_workbook_anti_copy.py`: likely absent on the current line; adapt tests to sanitized fixtures and current service APIs.

The principal risks are accidental fallback to baseline business values, overwriting manual adjustments during rerender, reverting current-run roster selection to the old baseline roster, and letting anti-copy code replace the current material-flow package logic.

## Integration strategy

1. Keep the current working tree and untracked user WIP untouched.
2. Commit this plan as a documentation-only integration checkpoint.
3. Apply `2dccd63` without accepting whole-file `ours`/`theirs` replacements; resolve the renderer, package, and service conflicts by preserving current flow and porting anti-copy semantics.
4. Apply `3954d9a` and resolve the manual-adjustment lifecycle at the current BusinessInput/Run boundary.
5. Add only the smallest missing architecture guards and sanitized regression tests.
6. Run targeted tests, full regression, Python/Node syntax checks, and diff checks.
7. Add the two formal 2026-09-21 UAT devlog files only after confirming they contain no sensitive data. Never add the four real-data screenshots.
8. Treat `uv.lock` separately: commit it only if repository history/documentation confirms uv is the project dependency-management standard; otherwise leave it untracked and report why.
9. Write `PAYROLL_BRANCH_INTEGRATION_RESULT.md`, commit the integration result, and leave `main` unchanged and the branch unpushed.

## Safety constraints

- Do not reset, clean, stash, delete, or push.
- Do not modify real Excel files.
- Do not commit real teacher, student, payroll, or screenshot data.
- Do not change AA/AC/AD/AE/AF business rules.
