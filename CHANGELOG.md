# Changelog

## Payroll Excel Adapter (Phase 2)

- Added read-only OOXML workbook inspection, layout fingerprints and formula/cache state reporting.
- Added source-cell provenance and read-only comment extraction to normalized records.
- Added adapters for the current raw schedule export, the two current payroll-sheet layouts and the final check workbook's normalized schedule/check records.
- Added a narrow current-August one-to-one reconciliation bridge and summary-only Excel CLI command.
- Added sanitized `.xlsx` fixtures and adapter tests for layout detection, moved columns, missing columns, missing formula caches, comments and a blocked unexplained difference.
- Ran a local read-only August dry-run and recorded only deidentified aggregate results.
- Did not modify, save or commit a real workbook or business-data export.

## Payroll Core V1

- Preserved the archived payroll Skill, scripts, references, 8-month assets and January legacy assets.
- Rechecked and documented the current payroll workflow.
- Added initial normalized data models and CSV adapters.
- Added a versioned YAML configuration layer with effective-period adjustments.
- Added a reconciliation engine with explicit statuses and coverage tracking.
- Added structured manual decisions.
- Added sanitized fixtures and pytest tests.
- Added a lightweight normalized-input CLI.
- Did not modify `main`, existing Skill files, existing business Python, or real business data.
