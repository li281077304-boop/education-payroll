# Payroll Branch Integration Result

## Integration branch

- Branch: `integration/payroll-20260921`
- Source baseline: `4817b41ab9e5f273fb76b58e4d787e36fd8c0b3f`
- Common ancestor with `ralph/ad-aa-ac-dde`: `4ccebdadefb7a256a060c5b99aef29b69e9a59e4`
- No push was performed.
- `main` was not modified.

## Integrated source semantics

The two missing source commits were inspected and integrated semantically rather than replacing newer high-churn files wholesale:

- `2dccd63de6a5d81afabbf4a8613b8d9bf9ce1242`: final-workbook anti-copy contract/model helpers, current-run rendering guards, empty-template/cache/comment protection, and sanitized regression coverage.
- `3954d9aeb5d3a2035a6cb39afbaa1ff1fad27b42`: Run-bound manual-adjustment lifecycle, active-status handling, renderer field override, provenance fields, and revoke regression coverage.

Because the current material-flow line had newer versions of `package.py`, `standard_payroll_render.py`, and `payroll_ui/service.py`, the original SHA commits are not literal ancestors of the result. Their required behavior is represented by the integration commits below; this is intentional semantic integration, not a silent whole-branch merge.

Integration commits:

1. `3b122e1` — integration plan.
2. `b9c7739` — workbook anti-copy semantics and sanitized contract helpers/tests.
3. `9b5c267` — production manual-adjustment binding/render/revoke path.
4. `74a357f` — sanitized 2026-09-21 UAT evidence.

## Capability preservation matrix

| Capability | Result |
|---|---|
| Four-material intake | Preserved from `4817b41`; not replaced by the older branch. |
| Drag/drop and paste UI | Preserved; existing regression remains green. |
| `.xls` / `.xlsx` / CSV intake and Chinese errors | Preserved; existing regression remains green. |
| Previous-month default and payroll-summary route | Preserved; existing regression remains green. |
| Baseline business values | Not used as a production fallback by the renderer. |
| Current-run roster | Renderer clears template data rows and writes only current Core rows. |
| Empty template | Historical row values/comments are cleared; formula-cache cleanup is covered. |
| Stale comments/formula cache | Cleared from reusable template rows; output is regenerated from current inputs. |
| Manual adjustment | Run-bound `MANUAL_ADJUSTMENT` with raw value, delta, final value, reason, evidence, actor and timestamp. |
| Revoke | `REVOKED` is accepted as a non-applyable status; removing the binding restores the raw current value. |

## Verification

- Targeted anti-copy/manual-adjustment tests: passed.
- Full regression: `385 passed, 1 skipped`.
- Skipped test: `tests/test_av_source_map.py:16`, because the real UAT template is unavailable; it is intentionally not a repository fixture.
- Node syntax check: passed.
- Python compile check: passed.
- `git diff --check`: passed.

## Untracked material and safety

- The two formal UAT evidence files under `devlog/2026-09-21/001-payroll-real-machine-uat/` were committed; they contain no teacher/student/payroll dataset.
- The four `artifacts/fresh-run-*.png` screenshots remain untracked and were not committed because they contain real UI/file information.
- The untracked `PAYROLL_FINAL_WORKBOOK_*` files remain excluded because they contain real-data paths/names from an older UAT line.
- `uv.lock` remains untracked. Repository history contains no committed lockfile and project docs prescribe `uv run --no-project`, not `uv sync`; it is therefore not treated as the dependency-management standard in this integration.
- No real Excel was modified or committed.
