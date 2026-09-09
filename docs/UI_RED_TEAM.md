# UI V1 reliability review

This review tests the local UI against the ways a payroll check can falsely
look complete.  It uses only sanitized fixtures.

| Risk | Result in V1 | Guard |
|---|---|---|
| A processed check workbook proves its own values | Blocked | AA/AC are calculated from the separately imported original schedule export; the optional final check workbook is never used as their authority source. |
| Wrong or unknown workbook is imported | Blocked | Workbook fingerprint and required-header validation reject it before a run accepts it. |
| Same workbook is assigned to two roles | Blocked | SHA-256 identity check rejects it. |
| Source file changes after checking | Blocked | SHA-256, size, and modification time move the run to `STALE`; decisions are cleared and recheck is refused until re-import. |
| A user clicks through issues and UI displays PASS | Blocked | Only Payroll Core field results can produce a status.  AE/AF/AV currently lack independent authority chains, so a complete payroll `PASS` is unavailable. |
| Formula cache or external workbook is stale | Visible | Material cards show formula-cache and external-reference counts; adapters preserve warnings instead of interpreting missing values as zero. |
| Human explanation silently overwrites Excel | Blocked | A decision is audit metadata only.  The UI does not edit or save imported workbooks. |
| Browser refresh loses a decision | Blocked | Runs, paths, hashes, issue metadata, and human decisions are stored in a local SQLite database. |
| Two runs for the same month | Allowed but visible | Each has a separate run ID and source hashes.  V1 does not silently merge them. |
| File moved or WPS rewrites it | Blocked | The stored path/hash fails freshness verification and the run becomes stale. |

## Remaining limits

The current UI uses the macOS native chooser.  Browser drag-and-drop is not
yet a separate import route.  More importantly, AE, AF, and AV are deliberately
not claimed as independently checked: their required upstream authorities are
not yet connected.
