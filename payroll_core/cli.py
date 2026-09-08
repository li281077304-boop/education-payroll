from __future__ import annotations

import argparse
from .adapters.payroll_sheet import read_payroll_csv
from .config.loader import load_config
from .excel.check_workbook import read_check_workbook_schedule
from .excel.payroll import read_payroll_excel
from .excel.reconciliation_bridge import actual_one_to_one_from_payroll, expected_one_to_one_from_normalized_schedule
from .excel.schedule import read_schedule_excel
from .reconcile.engine import ReconciliationEngine
from .reconcile.report import render_text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m payroll_core.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check")
    check.add_argument("--config", required=True)
    check.add_argument("--expected", required=True, help="normalized CSV with teacher,one_to_one,class_value")
    check.add_argument("--payroll", required=True, help="normalized payroll CSV")
    excel = sub.add_parser("excel-check")
    excel.add_argument("--config", required=True)
    excel.add_argument("--schedule", required=True, help="read-only raw schedule export")
    excel.add_argument("--check-workbook", required=True, help="read-only normalized payroll check workbook")
    excel.add_argument("--math-payroll", required=True, help="read-only math payroll workbook")
    excel.add_argument("--science-payroll", required=True, help="read-only science payroll workbook")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    if args.command == "excel-check":
        return _excel_check(args, config)
    expected_records = read_payroll_csv(args.expected, config.period)
    actual_records = read_payroll_csv(args.payroll, config.period)
    expected = {record.teacher: {"one_to_one": record.one_to_one, "class_value": record.class_value} for record in expected_records}
    actual = {record.teacher: {"one_to_one": record.one_to_one, "class_value": record.class_value} for record in actual_records}
    required = [(teacher, field) for teacher in sorted(set(expected) | set(actual)) for field in ("one_to_one", "class_value")]
    report = ReconciliationEngine(config).reconcile(expected, actual, required_fields=required, decisions=[])
    print(render_text(report))
    return 0 if report.summary and report.summary.overall_status == "PASS" else 1


def _excel_check(args, config) -> int:
    """Run a read-only, summary-only adapter chain; never print row values or names."""
    raw_schedule = read_schedule_excel(args.schedule, config.period)
    normalized_schedule = read_check_workbook_schedule(args.check_workbook, config.period)
    math_payroll = read_payroll_excel(args.math_payroll, config.period)
    science_payroll = read_payroll_excel(args.science_payroll, config.period)
    results = (raw_schedule, normalized_schedule, math_payroll, science_payroll)
    errors = sum(len(result.errors) for result in results)
    warnings = sum(len(result.warnings) for result in results)
    if errors:
        print("Payroll Excel Adapter")
        print(f"Adapter errors: {errors}")
        print(f"Adapter warnings: {warnings}")
        print("STATUS: REVIEW_REQUIRED")
        return 1
    expected, calculation_issues = expected_one_to_one_from_normalized_schedule(normalized_schedule.records)
    actual = actual_one_to_one_from_payroll([*math_payroll.records, *science_payroll.records])
    required = [(teacher, "one_to_one") for teacher in sorted(set(expected) | set(actual))]
    report = ReconciliationEngine(config).reconcile(expected, actual, required_fields=required)
    print("Payroll Excel Adapter")
    print(f"Raw schedule rows parsed: {len(raw_schedule.records)}")
    print(f"Normalized schedule rows parsed: {len(normalized_schedule.records)}")
    print(f"Payroll rows parsed: {len(actual)}")
    print(f"Formula cache missing or external references: {sum(result.coverage.get('formula_values_unresolved', 0) for result in results)}")
    print(f"Manual review required by adapters: {warnings + len(calculation_issues)}")
    print(render_text(report))
    return 0 if report.summary and report.summary.overall_status == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
