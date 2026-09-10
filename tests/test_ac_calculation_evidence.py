from openpyxl import load_workbook
from openpyxl.comments import Comment

from tests.test_payroll_ui_service import _prepared_run_with_values


def _class_issue(checked: dict) -> dict:
    return next(item for item in checked["issue_groups"] if "class_value" in item["affected_fields"])


def _replace_science_comment(service, run, science, text: str) -> None:
    workbook = load_workbook(science)
    sheet = workbook.active
    sheet["AC5"].comment = Comment(text, "审核人")
    workbook.save(science)
    service.import_file(run["id"], "science", str(science))


def test_ac_detail_values_sum_exactly_to_existing_system_ac(tmp_path):
    service, run, _, _, _ = _prepared_run_with_values(tmp_path, one_to_one=1.8, class_value=10)
    checked = service.check(run["id"])
    issue = _class_issue(checked)

    evidence = service.evidence(run["id"], issue["id"])

    calculation = evidence["ac_calculation"]
    assert calculation["system_total"] == sum(row["本条折算值"] for row in calculation["records"])
    record = next(row for row in evidence["field_records"] if row["field"] == "class_value")
    assert calculation["system_total"] == record["expected"]
    assert all(row["折算规则"] and row["来源位置"] for row in calculation["records"])


def test_structured_ac_comment_is_separate_evidence_and_compared(tmp_path):
    service, run, _, _, science = _prepared_run_with_values(tmp_path, one_to_one=1.8, class_value=10)
    _replace_science_comment(service, run, science, "AC：2.5")
    checked = service.check(run["id"])

    evidence = service.evidence(run["id"], _class_issue(checked)["id"])
    comparison = next(section for section in evidence["sections"] if section["title"] == "排课系统、工资表与人工批注的三方对照")
    comment = next(item for item in comparison["items"] if item.get("批注状态") == "STRUCTURED_COMMENT")

    assert comment["批注主张值"] == 2.5
    assert "系统 vs 批注" in comment
    assert "批注 vs 工资表" in comment
    assert evidence["ac_calculation"]["system_total"] != 2.5  # Comment never changes the source calculation.


def test_unstructured_ac_comment_is_not_guessed(tmp_path):
    service, run, _, _, science = _prepared_run_with_values(tmp_path, one_to_one=1.8, class_value=10)
    _replace_science_comment(service, run, science, "一人班特殊情况，待负责人核实")
    checked = service.check(run["id"])

    evidence = service.evidence(run["id"], _class_issue(checked)["id"])
    comparison = next(section for section in evidence["sections"] if section["title"] == "排课系统、工资表与人工批注的三方对照")
    comment = next(item for item in comparison["items"] if item.get("批注状态") == "COMMENT_NOT_STRUCTURED")

    assert "批注主张值" not in comment
    assert "一人班" in comment["人工批注原文"]


def test_labelled_grade_headcount_tally_is_a_structured_comment():
    # This has explicit grade, headcount and count for every item, rather than
    # an unlabelled number embedded in prose.
    assert _prepared_run_with_values  # fixture stays deliberately synthetic
    from payroll_ui.service import PayrollService
    assert PayrollService._structured_class_comment("九年级6人班×1；高二2人班×3") == 11.3
    assert PayrollService._structured_class_comment("九年级班课：\n6人班  1\n高二班课：\n2人班  3") == 11.3


def test_accepted_exception_survives_display_only_ac_evidence(tmp_path):
    service, run, _, _, _ = _prepared_run_with_values(tmp_path, one_to_one=1.8, class_value=10)
    checked = service.check(run["id"])
    issue = _class_issue(checked)
    service.decide(run["id"], issue["id"], "ACCEPTED_EXCEPTION", "审核人", "已确认的特殊折算", issue["fingerprint"])

    service.evidence(run["id"], issue["id"])
    reopened = service.get(run["id"])
    restored = next(item for item in reopened["issue_groups"] if item["id"] == issue["id"])

    assert restored["decision"]["action"] == "ACCEPTED_EXCEPTION"
    assert restored["decision"]["status"] == "ACTIVE"
