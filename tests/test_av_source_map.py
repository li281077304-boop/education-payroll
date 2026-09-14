"""Read-only AV source map contract tests."""
import json
import subprocess
from pathlib import Path

import pytest

from payroll_ui.service import AV_SOURCE_DEFINITIONS, PayrollService, _template_av_evidence


TEMPLATE = Path("/Users/macos/Desktop/payroll_read_test/薪资表模板.xlsx")


def test_template_av_evidence_reads_real_formula_without_mutation():
    if not TEMPLATE.is_file():
        pytest.skip("real UAT template is not available")
    evidence = _template_av_evidence(TEMPLATE)
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
