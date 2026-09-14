"""Content-based discovery for a local payroll material package.

The package is intentionally an index, not a copy of the source files.  It
records which local files were recognized and extracts only the small,
source-backed facts needed to open a generate Run: schedule rows, historical
grade evidence, historical payroll rating references, and AF policy evidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

from ..grade_inference import StudentGradeEvidence, normalize_lesson_start_time, split_student_names
from ..models.records import PayrollRecord, ScheduleRecord
from ..models.evidence import AdapterResult
from .check_workbook import read_check_workbook_schedule
from .common import date_from_time
from .inspect import inspect_workbook
from .payroll import read_payroll_excel
from .schedule import read_schedule_excel
from ..reconcile.payroll_scope import star_from_level
from ..source_registry import SourceRecord, SourceRegistry, SourceStatus, classify_source, file_hash
from ..adapters.assessment import read_assessment_report
from ..adapters.personnel import IdentityConflict, default_part_time_records, identity_conflicts, read_personnel
from ..adapters.refund import read_refund_report
from ..adapters.renewal_report import read_renewal_report
from ..adapters.star import read_star_report
from ..adapters.weekly_report import read_weekly_report


@dataclass(frozen=True)
class PackageFile:
    path: str
    name: str
    kind: str
    recognized: bool
    records: int = 0
    teachers: int = 0
    layout: str = ""
    notes: tuple[str, ...] = ()


@dataclass
class PayrollPackage:
    root: Path
    period: str
    files: list[PackageFile] = field(default_factory=list)
    schedule_path: Path | None = None
    grade_history_paths: list[Path] = field(default_factory=list)
    payroll_paths: list[Path] = field(default_factory=list)
    template_path: Path | None = None
    reference_ratings: dict[str, int] = field(default_factory=dict)
    rating_sources: dict[str, tuple[str, ...]] = field(default_factory=dict)
    authority_ratings: dict[str, int] = field(default_factory=dict)
    star_records: list[dict[str, Any]] = field(default_factory=list)
    star_conflicts: list[dict[str, Any]] = field(default_factory=list)
    policy_profiles: list[dict[str, Any]] = field(default_factory=list)
    scope_teachers: tuple[str, ...] = ()
    grade_evidence: list[StudentGradeEvidence] = field(default_factory=list)
    source_registry: list[dict[str, Any]] = field(default_factory=list)
    weekly_reports: list[dict[str, Any]] = field(default_factory=list)
    renewal_reports: list[dict[str, Any]] = field(default_factory=list)
    refund_reports: list[dict[str, Any]] = field(default_factory=list)
    assessment_reports: list[dict[str, Any]] = field(default_factory=list)
    personnel_records: list[dict[str, Any]] = field(default_factory=list)
    identity_conflicts: list[dict[str, Any]] = field(default_factory=list)
    inventory: dict[str, Any] = field(default_factory=dict)


def _file_hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _record_sheets(records: list[Any]) -> tuple[str, ...]:
    sheets = {
        getattr(record, "sheet", "")
        for record in records
        if getattr(record, "sheet", "")
    }
    sheets.update({
        getattr(evidence, "sheet", "")
        for record in records
        for evidence in getattr(record, "provenance", {}).values()
        if getattr(evidence, "sheet", "")
    })
    return tuple(sorted(sheets))


def _policy_from_record(record: PayrollRecord, period: str) -> dict[str, Any] | None:
    raw = record.provenance.get("af")
    formula = str(getattr(raw, "raw_value", "") or "").replace(" ", "").upper()
    if not formula.startswith("="):
        return None
    # Only accept the two formula families present in the source.  Anything
    # else remains unknown and cannot silently become a policy.
    if re.search(r"AD\d*-30\)\*AE", formula):
        deduction_enabled = True
        obligation_hours = 30.0
    elif re.search(r"AD\d*\*AE", formula):
        deduction_enabled = False
        obligation_hours = 0.0
    else:
        return None
    return {
        "teacher": record.teacher,
        "role": record.teacher_level or "教师",
        "employment_type": "FULL_TIME",
        "allow_no_teaching": False,
        "rating": None,
        "rating_override": None,
        "special_approval": "",
        "obligation_hours": obligation_hours,
        "obligation_hours_deduction_enabled": deduction_enabled,
        "note": "由历史工资表 AF 公式结构提取，待本期政策复核。",
        "effective_from": period,
        "effective_to": period,
        "source": f"历史工资表 AF 公式：{record.source}",
    }


def _grade_facts(path: Path, period: str) -> list[StudentGradeEvidence]:
    result = read_check_workbook_schedule(path, period)
    if result.errors:
        return []
    source_hash = _file_hash(path)
    facts: list[StudentGradeEvidence] = []
    for record in result.records:
        if not record.grade or not record.student or record.lesson_status and record.lesson_status != "已上课":
            continue
        lesson_date = date_from_time(record.lesson_time)
        if not lesson_date:
            continue
        grade_cell = record.provenance.get("grade")
        for student in split_student_names(record.student):
            facts.append(StudentGradeEvidence(
                student=student,
                lesson_date=lesson_date,
                grade=record.grade,
                source_file=str(path),
                source_hash=source_hash,
                sheet=getattr(grade_cell, "sheet", ""),
                coordinate=getattr(grade_cell, "coordinate", ""),
                origin="HISTORICAL_SCHEDULE",
                teacher=record.teacher,
                subject=record.subject,
                lesson_start_time=normalize_lesson_start_time(record.lesson_time),
                class_type=record.class_type,
            ))
    return facts


def _is_weekly_report_file(path: Path) -> bool:
    """Return whether a workbook is a week-scoped report, not a renewal source.

    A weekly teacher summary may contain a convenience “续费” column.  It is
    not the monthly renewal result requested by the operating-data adapter;
    treating it as one creates duplicate renewal rows and can produce rates
    above 100% because that report's “单科总数” has a different meaning.
    """
    text = path.stem.replace(" ", "")
    return bool(re.search(r"第\d+周|周报|周数据|weekly", text, flags=re.IGNORECASE))


def discover_payroll_package(root: str | Path, period: str, *, period_start: str | None = None, period_end: str | None = None) -> PayrollPackage:
    """Discover a package by workbook content and extract safe source facts."""
    directory = Path(root).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError("资料包目录不存在，请重新选择资料包文件夹。")
    package = PayrollPackage(root=directory, period=period)
    schedule_candidates: list[tuple[int, Path]] = []
    grade_candidates: list[Path] = []
    payroll_candidates: list[tuple[int, Path, list[PayrollRecord]]] = []
    all_facts: list[StudentGradeEvidence] = []
    registry = SourceRegistry()
    schedule_teacher_names: set[str] = set()

    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.name.startswith("~$"):
            continue
        # Hash once per physical input.  All semantic registrations below
        # reuse this digest and advertise one parse pass, even when a workbook
        # exposes more than one business view.
        digest = _file_hash(path)
        # Reset per-file inspection state before building the registration
        # closure.  Non-Excel inputs must never inherit the previous
        # workbook's layout, formula counts, or header evidence.
        inspection = None
        layout = ""

        def register_source(source_type: str, *, status: str | SourceStatus, evidence: dict[str, Any], sheets: tuple[str, ...] = ()) -> None:
            target_sheets = sheets or ("",)
            inspection_evidence = {
                "content": {"file_name": path.name, "file_hash": digest},
                "date": {"period": period},
                "formula": {
                    "count": sum(item.formula_count for item in inspection.records[0].sheets) if inspection and inspection.records else 0,
                    "external_count": sum(item.external_formula_count for item in inspection.records[0].sheets) if inspection and inspection.records else 0,
                    "missing_cache": sum(item.formula_cache_missing for item in inspection.records[0].sheets) if inspection and inspection.records else 0,
                },
                "historical_structure": {
                    "layout": layout,
                    "sheet_names": list(inspection.records[0].fingerprint.sheet_names) if inspection and inspection.records else [],
                    "matched_signals": list(inspection.records[0].fingerprint.matched_signals) if inspection and inspection.records else [],
                },
                "header": {
                    item.name: [{"row": row, "values": list(values)} for row, values in item.header_candidates]
                    for item in inspection.records[0].sheets
                } if inspection and inspection.records else {},
            }
            for sheet in target_sheets:
                registry.register(
                    source_type, period, path, sheet=sheet, status=status,
                    digest=digest,
                    source_evidence={
                        **inspection_evidence, **evidence, "physical_file_key": digest,
                        "parse_count": 1, "parsed_once": True,
                    },
                )

        suffix = path.suffix.lower()
        if suffix not in {".xlsx", ".xlsm", ".xls"}:
            package.files.append(PackageFile(str(path), path.name, "OTHER", False, notes=("非 Excel 输入，保留为资料包索引。",)))
            register_source("OTHER", status=SourceStatus.NEEDS_CONFIRMATION, evidence={"reason": "非 Excel 输入，未自动解析。"})
            continue
        try:
            inspection = inspect_workbook(path)
            layout = inspection.records[0].fingerprint.layout if inspection.records else ""
        except (OSError, ValueError):
            inspection, layout = None, ""
        if "模板" in path.stem:
            package.template_path = path
            package.files.append(PackageFile(str(path), path.name, "TEMPLATE", True, layout=layout))
            sheets = tuple(item.name for item in inspection.records[0].sheets) if inspection and inspection.records else ()
            register_source("PAYROLL_TEMPLATE", status=SourceStatus.RECOGNIZED, evidence={"layout": layout, "role": "template"}, sheets=sheets)
            continue
        if layout == "SCHEDULE_EXPORT_V1":
            try:
                parsed = read_schedule_excel(path, period, period_start=period_start, period_end=period_end)
                count = len(parsed.records)
                schedule_teacher_names.update(record.teacher for record in parsed.records if record.teacher)
                schedule_candidates.append((count, path))
                package.files.append(PackageFile(str(path), path.name, "SCHEDULE", not bool(parsed.errors), count, len({r.teacher for r in parsed.records}), layout, tuple(i.code for i in parsed.warnings)))
                sheets = _record_sheets(list(parsed.records)) or tuple(item.name for item in inspection.records[0].sheets) if inspection and inspection.records else ()
                register_source("SCHEDULE", status=SourceStatus.IMPORTED if not parsed.errors else SourceStatus.ERROR, evidence={"layout": layout, "records": count, "errors": [item.code for item in parsed.errors]}, sheets=sheets)
            except (OSError, ValueError) as exc:
                package.files.append(PackageFile(str(path), path.name, "SCHEDULE", False, layout=layout, notes=(str(exc),)))
                register_source("SCHEDULE", status=SourceStatus.ERROR, evidence={"layout": layout, "error": str(exc)})
            continue
        if layout == "PAYROLL_CHECK_V1":
            try:
                parsed = read_check_workbook_schedule(path, period)
                facts = _grade_facts(path, period)
                all_facts.extend(facts)
                grade_candidates.append(path)
                package.files.append(PackageFile(str(path), path.name, "GRADE_HISTORY", not bool(parsed.errors), len(parsed.records), len({r.teacher for r in parsed.records}), layout, tuple(i.code for i in parsed.warnings)))
                sheets = _record_sheets(list(parsed.records)) or tuple(item.name for item in inspection.records[0].sheets) if inspection and inspection.records else ()
                register_source("GRADE_HISTORY", status=SourceStatus.IMPORTED if not parsed.errors else SourceStatus.ERROR, evidence={"layout": layout, "records": len(parsed.records), "errors": [item.code for item in parsed.errors]}, sheets=sheets)
            except (OSError, ValueError) as exc:
                package.files.append(PackageFile(str(path), path.name, "GRADE_HISTORY", False, layout=layout, notes=(str(exc),)))
                register_source("GRADE_HISTORY", status=SourceStatus.ERROR, evidence={"layout": layout, "error": str(exc)})
            continue
        if layout == "PAYROLL_SHEET_V1":
            try:
                parsed = read_payroll_excel(path, period)
                if parsed.records:
                    payroll_candidates.append((len(parsed.records), path, list(parsed.records)))
                    package.files.append(PackageFile(str(path), path.name, "HISTORICAL_PAYROLL", True, len(parsed.records), len({r.teacher for r in parsed.records}), layout, tuple(i.code for i in parsed.warnings)))
                    sheets = _record_sheets(list(parsed.records)) or tuple(item.name for item in inspection.records[0].sheets) if inspection and inspection.records else ()
                    register_source("PAYROLL_BASELINE", status=SourceStatus.IMPORTED, evidence={"layout": layout, "records": len(parsed.records)}, sheets=sheets)
                    continue
            except (OSError, ValueError) as exc:
                package.files.append(PackageFile(str(path), path.name, "HISTORICAL_PAYROLL", False, layout=layout, notes=(str(exc),)))
                register_source("PAYROLL_BASELINE", status=SourceStatus.ERROR, evidence={"layout": layout, "error": str(exc)})
                continue
        # Business adapters are read-only and their normalized rows are kept in
        # this package object so later UI panels consume one parsed snapshot.
        adapter_errors: list[str] = []
        try:
            weekly = read_weekly_report(path, period)
        except Exception as exc:  # optional operating-data source must not block payroll
            weekly = AdapterResult()
            adapter_errors.append(f"WEEKLY_REPORT: {exc}")
        # Keep renewal as a distinct semantic view, but only from a monthly
        # renewal-capable workbook.  The shared row cache still guarantees
        # that the physical workbook is decoded once.
        try:
            renewal = read_renewal_report(path, period) if not _is_weekly_report_file(path) else AdapterResult()
        except Exception as exc:  # optional operating-data source must not block payroll
            renewal = AdapterResult()
            adapter_errors.append(f"RENEWAL: {exc}")
        try:
            personnel = read_personnel(path, period)
        except Exception as exc:  # optional operating-data source must not block payroll
            personnel = AdapterResult()
            adapter_errors.append(f"PERSONNEL: {exc}")
        refund = []
        try:
            refund = read_refund_report(path, period)
        except Exception as exc:  # optional operating-data source must not block payroll
            refund = []
            adapter_errors.append(f"REFUND: {exc}")
        try:
            assessment = read_assessment_report(path, period)
        except Exception as exc:  # optional operating-data source must not block payroll
            assessment = AdapterResult()
            adapter_errors.append(f"ASSESSMENT: {exc}")
        try:
            star = read_star_report(path, period)
        except Exception as exc:  # optional authority source must not block payroll
            star = AdapterResult()
            adapter_errors.append(f"STAR: {exc}")
        parsed_type = ""
        evidence: dict[str, Any] = {"layout": layout}
        if weekly.records:
            parsed_type = "WEEKLY_REPORT"
            package.weekly_reports.extend(item.as_dict() for item in weekly.records)
            evidence.update({
                "records": len(weekly.records),
                "features": ["WEEKLY_REPORT"],
                "value_authority": "FINAL_REPORTED_VALUE",
                "suggested_fields": ["suggested_total_students"],
            })
        if renewal.records:
            package.renewal_reports.extend(item.as_dict() for item in renewal.records)
            evidence.setdefault("features", []).append("RENEWAL")
            evidence["renewal_population_authority"] = "FINAL_REPORTED_VALUE"
            evidence["renewal_formula"] = "RENEWAL_COUNT / TOTAL_STUDENTS"
            if not parsed_type:
                parsed_type = "RENEWAL"
        if personnel.records:
            package.personnel_records.extend(item.as_dict() for item in personnel.records)
            package.identity_conflicts.extend(item.as_dict() for item in identity_conflicts(item.teacher for item in personnel.records))
            parsed_type = parsed_type or "PERSONNEL"
            evidence.setdefault("features", []).append("PERSONNEL")
        if refund:
            package.refund_reports.extend(item.as_dict() for item in refund)
            parsed_type = parsed_type or "REFUND"
            evidence.setdefault("features", []).append("REFUND")
        if assessment.records:
            package.assessment_reports.extend(item.as_dict() for item in assessment.records)
            parsed_type = parsed_type or "ASSESSMENT"
            evidence.setdefault("features", []).append("ASSESSMENT")
        elif assessment.coverage.get("recognized_fields"):
            # A department-level assessment can have explicit metric columns
            # but no person-level rows.  It is still a recognized assessment
            # source and must not fall through to REFUND/OTHER.
            parsed_type = parsed_type or "ASSESSMENT"
            evidence.setdefault("features", []).append("ASSESSMENT")
        if star.records:
            package.star_records.extend(item.as_dict() for item in star.records)
            parsed_type = parsed_type or "STAR"
            evidence.setdefault("features", []).append("STAR")
            evidence["authority"] = "SYSTEM_AUTHORITY"
        stem = path.stem
        kind = "MANAGEMENT_ASSESSMENT" if "考核" in stem or "最佳学科组" in stem else "OTHER_INPUT"
        notes = tuple(i.code for i in weekly.warnings + weekly.errors + renewal.warnings + renewal.errors + personnel.warnings + personnel.errors + assessment.warnings + assessment.errors) + tuple(adapter_errors)
        package.files.append(PackageFile(
            str(path), path.name, parsed_type or kind,
            bool(inspection and not inspection.errors)
            or bool(weekly.records or renewal.records or personnel.records or refund or assessment.records or star.records),
            records=(len(weekly.records) + len(renewal.records) + len(personnel.records)
                     + len(refund) + len(assessment.records) + len(star.records)),
            teachers=len({
                getattr(item, "teacher", "") or getattr(item, "person", "")
                for item in [*weekly.records, *renewal.records, *personnel.records, *refund, *assessment.records, *star.records]
                if getattr(item, "teacher", "") or getattr(item, "person", "")
            }),
            layout=layout,
            notes=notes,
        ))
        if parsed_type:
            semantic_records = list(weekly.records) + list(renewal.records) + list(personnel.records) + list(assessment.records) + list(star.records)
            sheets = _record_sheets(semantic_records)
            if not sheets:
                sheets = tuple(item.name for item in inspection.records[0].sheets) if inspection and inspection.records else (str(assessment.coverage.get("sheet", "")),)
            sheets = tuple(sheet for sheet in sheets if sheet)
            register_source(parsed_type, status=SourceStatus.IMPORTED, evidence=evidence, sheets=sheets)
            # A single parsed workbook may legitimately provide more than one
            # semantic source (for example weekly students and renewal counts).
            # They share the same file hash and parsed rows, but remain
            # separately addressable in the registry.
            for feature_type in ("RENEWAL" if renewal.records else "", "PERSONNEL" if personnel.records else "", "REFUND" if refund else "", "ASSESSMENT" if assessment.records else "", "STAR" if star.records else ""):
                if feature_type:
                    register_source(feature_type, status=SourceStatus.IMPORTED, evidence={"shared_parsed_source": parsed_type, "features": [feature_type]}, sheets=sheets)
        else:
            headers = tuple(value for item in (inspection.records[0].sheets if inspection and inspection.records else ()) for _row, values in item.header_candidates for value in values)
            source_type, signals = classify_source(file_name=path.name, layout=layout, headers=headers, text=stem)
            if adapter_errors:
                signals = {**signals, "adapter_errors": adapter_errors}
            status = SourceStatus.RECOGNIZED if source_type != "OTHER" else SourceStatus.NEEDS_CONFIRMATION
            sheets = tuple(item.name for item in inspection.records[0].sheets) if inspection and inspection.records else ()
            register_source(source_type, status=status, evidence={**signals, "layout": layout}, sheets=sheets)

    if not schedule_candidates:
        raise ValueError("资料包中没有识别到可用的本月排课表。")
    # Prefer the dated export over a normalized/check workbook when both are
    # present.  The normalized workbook is retained as grade evidence.
    schedule_candidates.sort(key=lambda item: ("排课列表" in item[1].stem, item[0]), reverse=True)
    package.schedule_path = schedule_candidates[0][1]
    package.grade_history_paths = grade_candidates
    package.payroll_paths = [path for _count, path, _records in payroll_candidates]
    package.grade_evidence = all_facts

    ratings: dict[str, set[int]] = {}
    rating_sources: dict[str, set[str]] = {}
    policies: dict[str, dict[str, Any]] = {}
    scope: set[str] = set()
    for _count, path, records in payroll_candidates:
        for record in records:
            scope.add(record.teacher)
            rating = star_from_level(record.teacher_level)
            if rating is not None:
                ratings.setdefault(record.teacher, set()).add(rating)
                rating_sources.setdefault(record.teacher, set()).add(path.name)
            policy = _policy_from_record(record, period)
            if policy:
                prior = policies.get(record.teacher)
                if prior is None:
                    policies[record.teacher] = policy
                elif (prior["obligation_hours_deduction_enabled"], prior["obligation_hours"]) != (policy["obligation_hours_deduction_enabled"], policy["obligation_hours"]):
                    policies.pop(record.teacher, None)
    package.reference_ratings = {teacher: next(iter(values)) for teacher, values in ratings.items() if len(values) == 1}
    package.rating_sources = {teacher: tuple(sorted(sources)) for teacher, sources in rating_sources.items()}
    authority_values: dict[str, set[int]] = {}
    authority_sources: dict[str, list[dict[str, Any]]] = {}
    for item in package.star_records:
        teacher = str(item.get("teacher", "")).strip()
        rating = item.get("rating")
        if not teacher or rating in (None, ""):
            continue
        authority_values.setdefault(teacher, set()).add(int(rating))
        authority_sources.setdefault(teacher, []).append(item)
    package.authority_ratings = {teacher: next(iter(values)) for teacher, values in authority_values.items() if len(values) == 1}
    package.star_conflicts = [
        {"teacher": teacher, "ratings": sorted(values), "sources": authority_sources.get(teacher, [])}
        for teacher, values in authority_values.items() if len(values) > 1
    ]
    if package.reference_ratings and package.payroll_paths:
        # Teacher-level stars extracted from a historical payroll are useful
        # reference data, but they are not the independent authority source;
        # keep them visible as pending verification rather than silently
        # presenting them as VERIFIED.
        star_path = package.payroll_paths[0]
        star_digest = _file_hash(star_path)
        registry.register("STAR", period, star_path, sheet="教学部", status=SourceStatus.NEEDS_CONFIRMATION, digest=star_digest, source_evidence={"records": len(package.reference_ratings), "authority": "UPLOAD_REFERENCE_NEEDS_VERIFICATION", "physical_file_key": star_digest, "parse_count": 1, "parsed_once": True})
    # The fixed part-time prices are a versioned, source-backed business rule
    # even when the local material package does not contain a separate
    # personnel workbook.  Only materialize names that actually occur in this
    # period's schedule; do not invent a personnel roster or merge 刘宇/刘雨.
    explicit_personnel_names = {item.get("teacher", "") for item in package.personnel_records}
    default_records = [
        item.as_dict()
        for item in default_part_time_records(period, source="内置兼职固定单价规则")
        if item.teacher in schedule_teacher_names and item.teacher not in explicit_personnel_names
    ]
    if default_records:
        package.personnel_records.extend(default_records)
        builtin_hash = sha256("内置兼职固定单价规则/v1".encode("utf-8")).hexdigest()
        registry.add(SourceRecord(
            source_type="PERSONNEL", period=period,
            file_name="内置兼职固定单价规则", file_hash=builtin_hash,
            sheet="PERSONNEL_RULES", status=SourceStatus.RECOGNIZED,
            source_evidence={
                "rule": "effective_dated_fixed_rate_per_lesson",
                "records": default_records,
                "parse_count": 1, "parsed_once": True,
            },
        ))
    # Identity must be checked against the schedule as well as an uploaded
    # personnel table: both names can appear in payroll material without
    # proving they are the same person.
    all_personnel_names = explicit_personnel_names | {item.get("teacher", "") for item in default_records}
    package.identity_conflicts = [
        item.as_dict()
        for item in identity_conflicts(all_personnel_names | schedule_teacher_names)
    ]
    package.source_registry = registry.as_dicts()
    package.policy_profiles = [value for teacher, value in sorted(policies.items()) if teacher in package.reference_ratings or teacher in scope]
    package.scope_teachers = tuple(sorted(scope))
    package.inventory = {
        "root": str(directory),
        "period": period,
        "schedule": str(package.schedule_path),
        "grade_history": [str(path) for path in package.grade_history_paths],
        "historical_payroll": [str(path) for path in package.payroll_paths],
        "template": str(package.template_path) if package.template_path else "",
        "reference_ratings": len(package.reference_ratings),
        "authority_ratings": len(package.authority_ratings),
        "star_records": len(package.star_records),
        "star_conflicts": package.star_conflicts,
        "policy_profiles": len(package.policy_profiles),
        "scope_teachers": len(package.scope_teachers),
        "grade_evidence": len(package.grade_evidence),
        "source_registry": package.source_registry,
        "physical_file_audit": registry.physical_file_audit(),
        "weekly_reports": len(package.weekly_reports),
        "renewal_reports": len(package.renewal_reports),
        "refund_reports": len(package.refund_reports),
        "assessment_reports": len(package.assessment_reports),
        "personnel_records": len(package.personnel_records),
        "identity_conflicts": package.identity_conflicts,
        "files": [item.__dict__ for item in package.files],
    }
    return package
