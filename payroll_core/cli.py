from __future__ import annotations

import argparse
from pathlib import Path

from .adapters.payroll_sheet import read_payroll_csv
from .config.loader import load_config
from .models.decisions import ManualDecision
from .reconcile.engine import ReconciliationEngine
from .reconcile.report import render_text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m payroll_core.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check")
    check.add_argument("--config", required=True)
    check.add_argument("--expected", required=True, help="normalized CSV with teacher,one_to_one,class_value")
    check.add_argument("--payroll", required=True, help="normalized payroll CSV")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "check":
        return 2
    config = load_config(args.config)
    expected_records = read_payroll_csv(args.expected, config.period)
    actual_records = read_payroll_csv(args.payroll, config.period)
    expected = {record.teacher: {"one_to_one": record.one_to_one, "class_value": record.class_value} for record in expected_records}
    actual = {record.teacher: {"one_to_one": record.one_to_one, "class_value": record.class_value} for record in actual_records}
    required = [(teacher, field) for teacher in sorted(set(expected) | set(actual)) for field in ("one_to_one", "class_value")]
    report = ReconciliationEngine(config).reconcile(expected, actual, required_fields=required, decisions=[])
    print(render_text(report))
    return 0 if report.summary and report.summary.overall_status == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
