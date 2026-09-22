"""Read-only AV source map contract tests."""
import json
import subprocess
from pathlib import Path

from openpyxl import load_workbook
from payroll_ui.service import AV_SOURCE_DEFINITIONS, PayrollService, _template_av_evidence
from tests.test_standard_payroll_output import _sanitized_template


def test_template_av_evidence_reads_sanitized_formula_without_mutation(tmp_path):
    template = _sanitized_template(tmp_path)
    book = load_workbook(template)
    sheet = book.active
    sheet["M5"] = "=(G5+H5+I5+J5)/K5*L5"
    sheet["AF5"] = "=(AD5-30)*AE5"
    sheet["AK5"] = "=AH5*1+AI5*1.5+AJ5*0.75"
    sheet["AV5"] = "=M5+AF5+AG5+AK5+AL5+AN5+AO5+AP5+AQ5+AR5+AS5+AT5+AU5+AM5"
    book.save(template)
    evidence = _template_av_evidence(template)
    assert evidence["exists"] is True
    assert evidence["formula"].startswith("=M5+AF5+AG5+AK5")
    assert evidence["field_formulas"]["M"] == "=(G5+H5+I5+J5)/K5*L5"
    assert evidence["field_formulas"]["AF"].startswith("=(AD5-30)*AE5")


def test_av_source_map_is_read_only_and_explicit(tmp_path):
    service = PayrollService(tmp_path)
    result = service.av_source_map()
    assert result["version"] == "AV_SOURCE_MAP/v1"
    assert result["components"] == ["M", "AF", "AG", "AK", "AL", "AM", "AN", "AO", "AP", "AQ", "AR", "AS", "AT", "AU"]
    assert result["direct_components"] == result["components"]
    assert result["upstream_dependencies"] == {"AK": ["AH", "AI", "AJ"]}
    assert result["full_payroll_completeness"]["total"] == 14
    assert {item["column"] for item in result["fields"]} == set(AV_SOURCE_DEFINITIONS)
    assert result["fields"][0]["column"] == "M"
    assert result["fields"][0]["category"] == "SOURCE_AVAILABLE_NOT_CONNECTED"
    assert result["fields"][-1]["category"] == "DERIVED_OUTPUT"
    assert result["fields"][-1]["current_system_status"] == "BLOCKED_BY_COMPONENTS"


def test_av_source_map_page_is_reachable_in_ui():
    node = __import__("shutil").which("node")
    if node is None:
        pytest.skip("Node is needed to exercise the production UI renderer")
    script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync(process.argv[1], 'utf8').split('(async () => {')[0];
const node = {innerHTML:''};
const context = {document:{querySelector(){return node;}}, window:{}, console};
vm.createContext(context); vm.runInContext(source, context);
const html = vm.runInContext(`avSourceMapPage`, context);
assert.equal(typeof html, 'function');
assert(source.includes('AV 直接组成项'));
assert(source.includes('上游依赖'));
assert(source.includes('BLOCKED_BY_COMPONENTS'));
'''
    app = Path(__file__).parents[1] / "payroll_ui" / "static" / "app.js"
    result = subprocess.run([node, "-e", script, str(app)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_av_source_map_promotes_m_to_determined_after_snapshot(tmp_path):
    service = PayrollService(tmp_path)
    run = service.create("2026-08", mode="GENERATE")
    run["generated_payroll"] = {"rows": [{"teacher": "教师甲", "final_fields": {
        "M": {"value": 6300, "state": "DETERMINED"},
        **{code: {"value": 0, "state": "NOT_APPLICABLE"} for code in ("AF", "AG", "AK", "AL", "AM", "AN", "AO", "AP", "AQ", "AR", "AS", "AT", "AU")},
    }}]}
    service.store.save(run)
    result = service.av_source_map(run["id"])
    m = next(item for item in result["fields"] if item["column"] == "M")
    assert m["current_system_status"] == "DETERMINED"
    assert m["category"] == "DETERMINED"
    assert result["full_payroll_completeness"] == {"complete": 14, "total": 14, "label": "14 / 14"}
