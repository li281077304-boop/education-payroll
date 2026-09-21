"""Run a source-driven final-workbook contract UAT.

This helper is an oracle/comparison tool. Production generation goes through
``render_generated_payroll`` with a current Run; it never uses this script as
a baseline-value source.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from payroll_core.excel.final_workbook_contract import render_final_workbook_contract, sha256_file


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", required=True)
    parser.add_argument("--renewal", required=True)
    parser.add_argument("--refund", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--evidence-dir", required=True)
    args = parser.parse_args()
    result = render_final_workbook_contract(
        template_path=args.template,
        renewal_path=args.renewal,
        refund_path=args.refund,
        output_path=args.output,
        evidence_dir=args.evidence_dir,
    )
    result["assets"] = {
        key: {"path": value, "sha256": sha256_file(value)}
        for key, value in {
            "template": args.template,
            "renewal": args.renewal,
            "refund": args.refund,
        }.items()
    }
    Path(args.evidence_dir, "FINAL_WORKBOOK_RESULT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": result["output_path"], "template_exact": result["template_diff"]["template_exact"], "business_unexplained": result["business_unexplained"], "comment_counts": result["comment_counts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
