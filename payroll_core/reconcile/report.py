from __future__ import annotations

import json
from dataclasses import asdict

from ..models.reconciliation import ReconciliationReport


def report_to_dict(report: ReconciliationReport) -> dict:
    return {
        "summary": asdict(report.summary) if report.summary else None,
        "items": [asdict(item) for item in report.items],
    }


def render_text(report: ReconciliationReport) -> str:
    if report.summary is None:
        raise ValueError("Report has not been finalized")
    summary = report.summary
    counts = summary.counts
    return "\n".join(
        [
            "Payroll Reconciliation",
            f"Coverage: {summary.coverage_percent:.2f}% ({summary.completed_checks}/{summary.required_checks})",
            f"MATCH: {counts.get('MATCH', 0)}",
            f"EXPLAINED: {counts.get('EXPLAINED_DIFFERENCE', 0)}",
            f"MANUAL REVIEW: {counts.get('NEEDS_MANUAL_REVIEW', 0)}",
            f"UNEXPLAINED: {counts.get('UNEXPLAINED_DIFFERENCE', 0)}",
            f"STATUS: {summary.overall_status}",
        ]
    )


def write_json(report: ReconciliationReport, path: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report_to_dict(report), handle, ensure_ascii=False, indent=2)
