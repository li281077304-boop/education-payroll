# Payroll real UAT bootstrap report

Run: `payroll-cua-big-loop-20260915`

The existing 17-item UAT evidence was reloaded in an isolated Ralph-owned worktree. Current regression run: `uv run --with '.[test]' pytest -q` → **374 passed**; `uv run python -m compileall -q payroll_core payroll_ui` → **PASS**; `git diff --check` → **PASS**.

Current bootstrap obligations remain **12 PASS, 0 TECHNICAL_OPEN, 5 HUMAN_BLOCKED, 0 FAILED**. A separate fresh production-path Run (`18a38d63ebcd`) has now been exercised against the real 2026-08 files; its detailed evidence is in `REAL_UAT_20260916.md`. That Run confirms AA/AC/AD/AE 51/51, but correctly leaves fresh AF policy confirmation, 32 M input gaps, renewal approval/identity, refund approval, and other AV rules as explicit business/source blocks. No prior Run confirmation was reused and no missing value was converted to zero.

The source adapters and normal export path were exercised directly and deterministic checks pass. Because no runnable technical work remains after this evidence pass, the deterministic scheduler is correctly `WAITING_FOR_HUMAN`; no new Worker turn, Machine Gate, checkpoint, or merge was fabricated. The original shared Payroll workspace remains untouched.
