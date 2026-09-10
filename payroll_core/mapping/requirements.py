"""Business modules declare which semantic fields they need.

The mapping engine only answers "which Excel column carries this field?".
It never decides what the business needs, so a new campus or subject group
never requires a new adapter.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldRequirement:
    """One semantic field a business module depends on."""

    field: str
    label: str
    aliases: tuple[str, ...]                 # exact header names that mean this field
    weak_tokens: tuple[str, ...] = ()        # substrings that make a column a *candidate*
    required: bool = True
    kind: str = "text"                       # text | count | grade | class_type | subject


@dataclass(frozen=True)
class ImportRequirement:
    """A named set of fields, owned by the consuming business module."""

    name: str
    fields: tuple[FieldRequirement, ...]

    @property
    def required_fields(self) -> tuple[FieldRequirement, ...]:
        return tuple(item for item in self.fields if item.required)

    def field(self, name: str) -> FieldRequirement:
        return next(item for item in self.fields if item.field == name)


#: Fields the schedule / AC reconciliation truly depends on.
#: A two-hour default applies to every course, so duration, teaching hours and
#: start/end times are deliberately absent: they must never block an import.
SCHEDULE_AC_REQUIREMENT = ImportRequirement(
    name="SCHEDULE_AC",
    fields=(
        FieldRequirement("teacher", "任课老师", ("任课老师", "教师", "教师姓名", "授课教师", "老师"), ("老师", "教师")),
        FieldRequirement("grade", "年级", ("年级", "所属年级", "上课年级"), (), True, "grade"),
        FieldRequirement("subject", "学科", ("学科", "科目", "上课科目"), (), True, "subject"),
        FieldRequirement("class_type", "课程所属班型", ("课程所属班型", "班型", "课程班型", "教学形式", "课程类型", "班级类型"), ("班型", "类型", "形式"), True, "class_type"),
        FieldRequirement("actual_student_count", "实到人数", ("实到人数", "到课人数", "实际到课人数", "实到"), ("人数",), True, "count"),
        # Optional context. Missing values here must never block an import.
        FieldRequirement("student", "上课学员", ("上课学员", "学生", "学员", "学生姓名"), (), False),
        FieldRequirement("lesson_time", "上课时间", ("上课时间", "上课日期", "授课时间", "时间"), (), False),
        FieldRequirement("class_name", "上课班级", ("上课班级", "班级名称", "班级"), (), False),
        FieldRequirement("lesson_status", "上课状态", ("上课状态", "状态"), (), False),
    ),
)
