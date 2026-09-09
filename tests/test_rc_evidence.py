"""Evidence is selected from the same authorities as Core, not payroll labels."""
from dataclasses import replace
from payroll_core.models.records import PayrollRecord
from payroll_core.models.evidence import SourceEvidence, CellValueState
from payroll_ui.service import PayrollService


def test_ae_af_detail_uses_separate_authorities_and_shows_complete_chain(tmp_path):
    service = PayrollService(tmp_path)
    service.save_rating_version("2025-10", "2026-09", "合成星级资料", "synthetic-v1", [{"teacher": "教师甲", "rating": 3}])
    service.save_policy_version("2025-10", "2026-09", "合成个人政策", [{"teacher": "教师甲", "role": "兼职MT", "rating": 3, "rating_override": 4, "special_approval": "人工构造特批", "obligation_hours": 30, "obligation_hours_deduction_enabled": True}])
    run = service.create("2026-08")
    target = PayrollRecord("2026-08", "教师甲", teaching_hours=70, ae=32, af=1280, provenance={
        "teaching_hours": SourceEvidence("fake_payroll.xlsx", "工资", "AD5", "AD", 70, 70, CellValueState.RAW_VALUE),
        "ae": SourceEvidence("fake_payroll.xlsx", "工资", "AE5", "AE", 32, 32, CellValueState.RAW_VALUE),
        "af": SourceEvidence("fake_payroll.xlsx", "工资", "AF5", "AF", 1280, 1280, CellValueState.RAW_VALUE),
    })
    sections = service._evidence_sections(run, {"teacher": "教师甲", "affected_fields": ["rate", "af_policy"]}, [], target)
    by_title = {x["title"]: x["items"] for x in sections}
    ae = by_title["AE 规则链"]
    af = by_title["AF 规则链"]
    assert ae[0]["适用星级"] == 3
    assert af[0]["适用星级"] == 4
    assert ae[0]["命中规则数"] == af[0]["命中规则数"] == 1
    assert ae[1]["星级加成"] == 5
    assert af[1]["星级加成"] == 10
    assert af[2]["计算过程"] == "(70 - 30.0) × (32 + 10)"
    assert af[2]["特批说明"] == "人工构造特批"
    assert "仍来自工资表自身" in by_title["独立性边界"][0]["AD"]
    assert {x["来源位置"] for x in by_title["工资表目标与 AD 来源"]} == {"AD5", "AE5", "AF5"}
    expired = service._evidence_sections({**run, "period": "2026-10"}, {"teacher": "教师甲", "affected_fields": ["rate", "af_policy"]}, [], target)
    for section in expired:
        if section["title"] in {"AE 规则链", "AF 规则链"}:
            assert section["items"][0]["命中规则数"] == 0
