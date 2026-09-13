from pathlib import Path
from shutil import copyfile
from threading import Thread
from urllib.request import Request, urlopen
import json

from openpyxl import load_workbook

from payroll_ui.server import PayrollHttpServer
from payroll_ui.service import PayrollService


FIXTURES = Path(__file__).parent / "fixtures" / "excel"


def _star_package_book(path: Path, rows: list[tuple[str, str]]) -> Path:
    book = load_workbook(FIXTURES / "fake_payroll.xlsx")
    sheet = book.active
    sheet.delete_rows(1, sheet.max_row)
    sheet.append(["星级教师具体名单"])
    sheet.append(["", "三星", "", "四星", ""])
    sheet.append(["", "姓名", "学科", "姓名", "学科"])
    for name, subject in rows:
        sheet.append(["", name, subject, "", ""])
    book.save(path)
    return path


def test_package_star_authority_is_bound_to_run_and_core(tmp_path):
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    schedule = package_dir / "排课列表.xlsx"
    from shutil import copyfile
    copyfile(FIXTURES / "fake_schedule.xlsx", schedule)
    _star_package_book(package_dir / "星级名单.xlsx", [("张三", "数学"), ("李四", "物理")])

    service = PayrollService(tmp_path / "app-data")
    run = service.create("2026-08", mode="GENERATE")
    imported = service.import_package(run["id"], str(package_dir))["run"]

    assert imported["authority_ratings"] == {"张三": 3, "李四": 3}
    rating = service.store.get_rating_version(imported["rating_version_id"])
    assert rating["source"] == "资料包系统权威星级"
    assert imported["authority_context"]["rating"]["source"] == "资料包系统权威星级"
    checked = service.check(imported["id"])
    rows = {row["teacher"]: row for row in checked["core_calculation"]["rows"]}
    assert rows["张三"]["fields"]["AE"]["state"] == "DETERMINED"
    assert rows["张三"]["fields"]["AE"]["evidence"][0]["kind"] == "RATING_AUTHORITY"


def test_package_star_conflict_is_preserved_without_binding_conflicting_teacher(tmp_path):
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    from shutil import copyfile
    copyfile(FIXTURES / "fake_schedule.xlsx", package_dir / "排课列表.xlsx")
    _star_package_book(package_dir / "星级名单-3.xlsx", [("张三", "数学")])
    # A second independent source disagrees for the same teacher.
    book = load_workbook(package_dir / "星级名单-3.xlsx")
    sheet = book.active
    sheet["B2"] = "四星"
    book.save(package_dir / "星级名单-4.xlsx")

    service = PayrollService(tmp_path / "app-data")
    service.save_rating_version("2026-08", "2026-08", "旧绑定星级", "old", [{"teacher": "张三", "rating": 2}])
    run = service.create("2026-08", mode="GENERATE")
    imported = service.import_package(run["id"], str(package_dir))["run"]
    assert imported["star_conflicts"][0]["teacher"] == "张三"
    assert imported.get("star_authority_status") == "CONFLICT_NEEDS_CONFIRMATION"
    assert imported.get("rating_version_id") is None


def test_package_personnel_rates_bind_to_the_same_run_calculation_version(tmp_path):
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    from shutil import copyfile
    copyfile(FIXTURES / "fake_schedule.xlsx", package_dir / "排课列表.xlsx")
    book = load_workbook(FIXTURES / "fake_payroll.xlsx")
    sheet = book.active
    sheet.delete_rows(1, sheet.max_row)
    sheet.append(["姓名", "雇佣类型", "每节单价", "生效开始", "生效结束"])
    sheet.append(["张三", "兼职", 140, "2026-08", "2026-08"])
    book.save(package_dir / "人员资料.xlsx")

    service = PayrollService(tmp_path / "app-data")
    run = service.create("2026-08", mode="GENERATE")
    imported = service.import_package(run["id"], str(package_dir))["run"]
    assert imported["part_time_rate_version_id"]
    rate_version = next(item for item in service.part_time_rate_versions() if item["id"] == imported["part_time_rate_version_id"])
    assert rate_version["profiles"][0]["rate_per_session"] == 140


def test_package_star_fingerprint_changes_when_teacher_changes_in_same_cell(tmp_path):
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    from shutil import copyfile
    copyfile(FIXTURES / "fake_schedule.xlsx", package_dir / "排课列表.xlsx")
    star = package_dir / "星级名单.xlsx"
    _star_package_book(star, [("张三", "数学")])
    service = PayrollService(tmp_path / "app-data")
    run = service.create("2026-08", mode="GENERATE")
    first = service.import_package(run["id"], str(package_dir))["run"]["rating_version_id"]
    book = load_workbook(star)
    book.active["B4"] = "李四"
    book.save(star)
    second = service.import_package(run["id"], str(package_dir))["run"]["rating_version_id"]
    assert second != first


def _payroll_with_only(path: Path, row: int) -> None:
    copyfile(FIXTURES / "fake_payroll.xlsx", path)
    book = load_workbook(path)
    sheet = book.active
    for remove in sorted(({5, 6} - {row}), reverse=True):
        sheet.delete_rows(remove)
    book.save(path)


def _prepared_run(tmp_path: Path):
    schedule = tmp_path / "schedule.xlsx"; copyfile(FIXTURES / "fake_schedule.xlsx", schedule)
    math = tmp_path / "math.xlsx"; _payroll_with_only(math, 5)
    science = tmp_path / "science.xlsx"; _payroll_with_only(science, 6)
    service = PayrollService(tmp_path / "app-data")
    run = service.create("2026-08")
    for role, path in (("schedule", schedule), ("math", math), ("science", science)):
        run = service.import_file(run["id"], role, str(path))
    return service, run, schedule


def _prepared_run_with_values(tmp_path: Path, one_to_one: float = 36, class_value: float = 10):
    """Build a complete, artificial three-file run without real payroll data."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    schedule = tmp_path / "schedule.xlsx"
    copyfile(FIXTURES / "fake_schedule.xlsx", schedule)
    source = tmp_path / "combined.xlsx"
    copyfile(FIXTURES / "fake_payroll.xlsx", source)
    book = load_workbook(source)
    sheet = book.active
    sheet["AA5"] = one_to_one
    sheet["AC6"] = class_value
    book.save(source)
    math = tmp_path / "math.xlsx"
    science = tmp_path / "science.xlsx"
    _payroll_with_only_from(source, math, 5)
    _payroll_with_only_from(source, science, 6)
    service = PayrollService(tmp_path / "app-data")
    run = service.create("2026-08")
    for role, path in (("schedule", schedule), ("math", math), ("science", science)):
        run = service.import_file(run["id"], role, str(path))
    return service, run, schedule, math, science


def _payroll_with_only_from(source: Path, path: Path, row: int) -> None:
    copyfile(source, path)
    book = load_workbook(path)
    sheet = book.active
    for remove in sorted(({5, 6} - {row}), reverse=True):
        sheet.delete_rows(remove)
    book.save(path)


def test_ui_run_never_passes_when_ae_af_av_have_no_independent_authority(tmp_path):
    service, run, _ = _prepared_run(tmp_path)

    result = service.check(run["id"])

    assert result["status"] == "REVIEW_REQUIRED"
    states = {row["field"]: row["state"] for row in result["field_status"]}
    assert "rate" in states and "af_policy" in states
    assert "待AD独立来源" not in states["rate"]
    assert all(row["fields"]["AD"]["state"] == "DETERMINED" for row in result["core_calculation"]["rows"])
    assert states["av"] == "仅读取 / 待人工确认"


def test_ui_does_not_treat_other_subject_teachers_in_a_campus_schedule_export_as_missing_targets(tmp_path):
    service, run, schedule = _prepared_run(tmp_path)
    book = load_workbook(schedule)
    sheet = book.active
    sheet.append(["高一小班", "集体课程", "集体班", "测试校区", "2026-08-08 10:00~12:00", "2小时", "已上课", "无关教师", 2, 2, "学生丙", "01-数学", "线下课", "测试教室", "无关教师"])
    book.save(schedule)
    # Re-import records the revised source hash before checking it.
    run = service.import_file(run["id"], "schedule", str(schedule))

    result = service.check(run["id"])

    assert not any(item["teacher"] == "无关教师" and item["status"] == "MISSING_TARGET" for item in result["issues"])


def test_ui_marks_run_stale_when_original_file_changes(tmp_path):
    service, run, schedule = _prepared_run(tmp_path)
    with schedule.open("ab") as handle:
        handle.write(b"changed")

    result = service.get(run["id"])

    assert result["status"] == "STALE"


def test_special_decision_is_rechecked_not_used_to_force_full_pass(tmp_path):
    service, run, _ = _prepared_run(tmp_path)
    checked = service.check(run["id"])
    issue = next(item for item in checked["issues"] if item["field"] == "class_value")

    service.decide(run["id"], issue["id"], "special", "审核人", "脱敏的特殊班型说明")
    rechecked = service.check(run["id"])

    assert rechecked["status"] == "REVIEW_REQUIRED"
    assert next(item for item in rechecked["field_status"] if item["field"] == "class_value")["state"] == "已核对"


def test_loopback_ui_bootstrap_and_create_run(tmp_path):
    static = Path(__file__).parents[1] / "payroll_ui" / "static"
    server = PayrollHttpServer(("127.0.0.1", 0), PayrollService(tmp_path / "app-data"), static)
    worker = Thread(target=server.serve_forever, daemon=True); worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        token = json.loads(urlopen(base + "/api/bootstrap").read())["token"]
        request = Request(base + "/api/runs", data=b'{"period":"2026-08"}', method="POST", headers={"Content-Type": "application/json", "X-Payroll-Token": token})
        payload = json.loads(urlopen(request).read())
        assert payload["period"] == "2026-08"
    finally:
        server.shutdown(); server.server_close(); worker.join()


def _post_json(base: str, token: str, path: str, payload: dict) -> dict:
    request = Request(
        base + path,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "X-Payroll-Token": token},
    )
    return json.loads(urlopen(request).read())


def test_loopback_fixture_flow_keeps_an_unexplained_difference_visible(tmp_path):
    _, _, schedule, math, science = _prepared_run_with_values(tmp_path / "files", one_to_one=1.2, class_value=2.16)
    static = Path(__file__).parents[1] / "payroll_ui" / "static"
    server = PayrollHttpServer(("127.0.0.1", 0), PayrollService(tmp_path / "web-data"), static)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        token = json.loads(urlopen(base + "/api/bootstrap").read())["token"]
        run = _post_json(base, token, "/api/runs", {"period": "2026-08"})
        for role, file_path in (("schedule", schedule), ("math", math), ("science", science)):
            run = _post_json(base, token, f"/api/runs/{run['id']}/files", {"role": role, "path": str(file_path)})
        checked = _post_json(base, token, f"/api/runs/{run['id']}/check", {})
        issue = next(item for item in checked["issues"] if item["field"] == "one_to_one")
        assert checked["status"] == "REVIEW_REQUIRED"
        assert issue["difference"] == -0.6
        evidence_request = Request(base + f"/api/runs/{run['id']}/evidence?issue={issue['id']}", headers={"X-Payroll-Token": token})
        evidence = json.loads(urlopen(evidence_request).read())
        assert len(evidence["evidence"]) >= 2
    finally:
        server.shutdown(); server.server_close(); worker.join()


def test_sanitized_happy_path_marks_aa_and_ac_as_independently_checked(tmp_path):
    service, run, *_ = _prepared_run_with_values(tmp_path, one_to_one=1.8, class_value=2.16)

    result = service.check(run["id"])
    fields = {item["field"]: item for item in result["field_status"]}

    assert result["summary"]["automatic_pass"] is True
    assert result["status"] == "REVIEW_REQUIRED"  # AE/AF/AV are deliberately not over-claimed.
    assert fields["one_to_one"]["state"] == "已核对"
    assert fields["class_value"]["state"] == "已核对"
    assert fields["one_to_one"]["authority"] is True
    assert fields["class_value"]["compared"] is True


def test_sanitized_one_to_one_difference_has_values_and_source_evidence(tmp_path):
    service, run, *_ = _prepared_run_with_values(tmp_path, one_to_one=1.2, class_value=2.16)
    checked = service.check(run["id"])
    issue = next(item for item in checked["issues"] if item["field"] == "one_to_one")

    assert issue["status"] == "UNEXPLAINED_DIFFERENCE"
    assert issue["expected"] == 1.8
    assert issue["actual"] == 1.2
    assert issue["difference"] == -0.6
    evidence = service.evidence(run["id"], issue["id"])
    assert any(row["来源"] == "原始排课" and row["来源位置"] for row in evidence["evidence"])
    assert any(row["来源"] == "工资表" and row["来源位置"] for row in evidence["evidence"])


def test_sanitized_class_difference_is_visible_as_a_blocker(tmp_path):
    service, run, *_ = _prepared_run_with_values(tmp_path, one_to_one=1.8, class_value=10)
    checked = service.check(run["id"])
    issue = next(item for item in checked["issues"] if item["field"] == "class_value")

    assert checked["status"] == "REVIEW_REQUIRED"
    assert issue["status"] == "UNEXPLAINED_DIFFERENCE"
    assert issue["difference"] == 7.84


def test_special_confirmation_persists_after_restart_and_never_forces_pass(tmp_path):
    service, run, *_ = _prepared_run_with_values(tmp_path, one_to_one=1.2, class_value=2.16)
    checked = service.check(run["id"])
    issue = next(item for item in checked["issues"] if item["field"] == "one_to_one")

    saved = service.decide(run["id"], issue["id"], "special", "审核人", "脱敏的特殊说明")
    assert next(item for item in saved["issues"] if item["id"] == issue["id"])["decision_label"] == "已确认特殊情况"
    restarted = PayrollService(tmp_path / "app-data").get(run["id"])
    assert restarted["decisions"][0]["reason"] == "脱敏的特殊说明"
    rechecked = PayrollService(tmp_path / "app-data").check(run["id"])
    assert rechecked["status"] == "REVIEW_REQUIRED"
    assert rechecked["summary"]["automatic_pass"] is True


def test_stale_file_blocks_old_results_and_reimport_recovers(tmp_path):
    service, run, schedule, *_ = _prepared_run_with_values(tmp_path, one_to_one=36, class_value=2.4)
    checked = service.check(run["id"])
    issue = checked["issues"][0]
    book = load_workbook(schedule)
    book.active["N2"] = "已变更的测试教室"
    book.save(schedule)

    stale = service.get(run["id"])
    assert stale["status"] == "STALE"
    assert stale["stale_files"] == ["schedule"]
    try:
        service.evidence(run["id"], issue["id"])
    except ValueError as exc:
        assert "原始文件已变化" in str(exc)
    else:
        raise AssertionError("stale run must block evidence")
    recovered = service.import_file(run["id"], "schedule", str(schedule))
    assert recovered["status"] == "FILES_READY"
    assert service.check(run["id"])["status"] == "REVIEW_REQUIRED"


def test_check_failure_returns_to_a_recoverable_material_state(tmp_path):
    service, run, *_ = _prepared_run_with_values(tmp_path, one_to_one=36, class_value=2.4)
    duplicate = tmp_path / "duplicate.xlsx"
    _payroll_with_only(duplicate, 5)
    service.import_file(run["id"], "science", str(duplicate))

    try:
        service.check(run["id"])
    except ValueError as exc:
        assert "重复教师" in str(exc)
    else:
        raise AssertionError("duplicate teachers must fail visibly")
    recovered = service.get(run["id"])
    assert recovered["status"] == "FILES_READY"
    assert "重复教师" in recovered["last_error"]


def test_browser_shell_uses_plain_language_for_core_workflow():
    source = (Path(__file__).parents[1] / "payroll_ui" / "static" / "app.js").read_text()
    for technical_word in ("Adapter", "Fingerprint", "Coverage", "Payroll Core"):
        assert technical_word not in source
    for plain_label in ("材料准备", "核对结果", "待处理问题", "管理岗位确认", "排课项目完成度"):
        assert plain_label in source


def test_run_binds_effective_rating_version_and_reports_a_rating_mismatch(tmp_path):
    service = PayrollService(tmp_path / "app-data")
    versions = service.save_rating_version("2025-10", "2026-09", "脱敏年度星级评定", "2025-10", [{"teacher": "张三", "rating": 4}])
    assert len(versions) == 1
    run = service.create("2026-08")
    assert run["rating_version_id"] == versions[0]["id"]
    # A later annual version must not replace the historical binding.
    service.save_rating_version("2026-10", "2027-09", "脱敏年度星级评定", "2026-10", [{"teacher": "张三", "rating": 3}])
    assert service.get(run["id"])["rating_version_id"] == versions[0]["id"]


def test_blank_rating_policy_is_saved_with_the_rating_version(tmp_path):
    service = PayrollService(tmp_path / "app-data")
    version = service.save_rating_version(
        "2025-10",
        "2026-09",
        "脱敏兼职政策",
        "2025-10",
        [{"teacher": "教师甲", "rating": 1, "role": "兼职MT", "allow_blank_payroll_rating": True}],
    )[0]

    assert version["ratings"][0]["allow_blank_payroll_rating"] is True


def test_baseline_final_payroll_values_are_checked_only_for_submitted_teachers(tmp_path):
    service, run, schedule, math, science = _prepared_run_with_values(tmp_path, one_to_one=1.2, class_value=2.16)
    baseline = tmp_path / "baseline.xlsx"
    copyfile(FIXTURES / "fake_payroll.xlsx", baseline)
    book = load_workbook(baseline)
    book.active["AA5"] = 1.8
    book.active["AC6"] = 2.16
    book.save(baseline)
    service.import_file(run["id"], "baseline", str(baseline))

    checked = service.check(run["id"])

    assert not any(item["field"] == "one_to_one" and item["teacher"] == "张三" for item in checked["issues"])
    assert {item["teacher"] for item in checked["issues"] if item["field"] in {"one_to_one", "class_value"}} <= {"张三", "李四"}


def test_one_submission_sheet_is_enough_to_start_a_group_run(tmp_path):
    service = PayrollService(tmp_path / "app-data")
    schedule = tmp_path / "schedule.xlsx"; copyfile(FIXTURES / "fake_schedule.xlsx", schedule)
    math = tmp_path / "math.xlsx"; _payroll_with_only(math, 5)
    run = service.create("2026-08")
    service.import_file(run["id"], "schedule", str(schedule))
    ready = service.import_file(run["id"], "math", str(math))

    assert ready["status"] == "FILES_READY"
    assert ready["health"]["ready"] is True


def test_baseline_formula_issues_outside_submitted_scope_are_not_group_issues(tmp_path):
    service, run, *_ = _prepared_run_with_values(tmp_path, one_to_one=1.8, class_value=2.16)
    baseline = tmp_path / "baseline.xlsx"
    copyfile(FIXTURES / "fake_payroll.xlsx", baseline)
    book = load_workbook(baseline)
    sheet = book.active
    sheet["A7"] = "范围外教师"
    for col in ("AA", "AC", "AD", "AE", "AV"):
        sheet[f"{col}7"] = 1
    sheet["AF7"] = 100  # an intentional formula anomaly outside this group run
    book.save(baseline)
    service.import_file(run["id"], "baseline", str(baseline))

    checked = service.check(run["id"])

    assert not any(item["field"] == "formula" for item in checked["issues"])


def test_no_deduction_profile_allows_the_matching_af_formula_exception(tmp_path):
    service = PayrollService(tmp_path / "app-data")
    schedule = tmp_path / "schedule.xlsx"; copyfile(FIXTURES / "fake_schedule.xlsx", schedule)
    math = tmp_path / "math.xlsx"; _payroll_with_only(math, 5)
    run = service.create("2026-08")
    service.import_file(run["id"], "schedule", str(schedule))
    service.import_file(run["id"], "math", str(math))
    baseline = tmp_path / "baseline.xlsx"; copyfile(FIXTURES / "fake_payroll.xlsx", baseline)
    book = load_workbook(baseline); book.active["AF6"] = "=(AD6-30)*AE6"; book.save(baseline)
    service.import_file(run["id"], "baseline", str(baseline))
    policy = service.save_policy_version(
        "2025-10", "2026-09", "脱敏例外政策", [{
            "teacher": "张三", "role": "兼职MT", "rating": 1,
            "obligation_hours": 30, "obligation_hours_deduction_enabled": False,
            "special_approval": "不扣义务课时",
        }],
    )[0]
    stored = service.store.get(run["id"]); stored["policy_version_id"] = policy["id"]; service.store.save(stored)

    checked = service.check(run["id"])

    assert not any(item["field"] == "formula" and item["status"] == "FORMULA_PATTERN_MISMATCH" for item in checked["issues"])


def test_replacing_schedule_clears_coordinate_bound_grade_resolutions(tmp_path):
    service, run, schedule = _prepared_run(tmp_path)
    stored = service.store.get(run["id"])
    stored["schedule_grade_resolutions"] = [{"class_name_cell": "A2", "grade": "高三"}]
    service.store.save(stored)

    service.import_file(run["id"], "schedule", str(schedule))

    assert "schedule_grade_resolutions" not in service.store.get(run["id"])
