"""Versioned deterministic comment templates for reviewed payroll evidence."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class CommentTemplate:
    kind: str
    version: str
    template: str

    def render(self, values: Mapping[str, Any]) -> str:
        class Safe(dict):
            def __missing__(self, key: str) -> str:
                return ""
        return self.template.format_map(Safe({key: "" if value is None else value for key, value in values.items()})).strip()


TEMPLATES = {
    "REFUND_NOTE": CommentTemplate("REFUND_NOTE", "v1", "{period}退费：{note}。来源：{source_label}"),
    "SOURCE_CORRECTION_NOTE": CommentTemplate("SOURCE_CORRECTION_NOTE", "v1", "{course_label}因{reason}，本月按{corrected_value}口径核算；系统重算后班课折算{system_value}小时。"),
    "APPROVED_OVERRIDE_NOTE": CommentTemplate("APPROVED_OVERRIDE_NOTE", "v1", "{course_label}经批准按{approved_treatment}核算；本月班课折算按{system_value}小时计入。"),
    "CLASS_COURSE_DIFFERENCE_NOTE": CommentTemplate("CLASS_COURSE_DIFFERENCE_NOTE", "v1", "{period}班课核对说明：{note}"),
    "OTHER": CommentTemplate("OTHER", "v1", "{note}"),
}


def render_comment(kind: str, values: Mapping[str, Any]) -> tuple[str, str]:
    template = TEMPLATES.get(kind)
    if template is None:
        raise ValueError("未知批注模板类型。")
    content = template.render(values)
    if not content:
        raise ValueError("批注内容不能为空。")
    return content, template.version
