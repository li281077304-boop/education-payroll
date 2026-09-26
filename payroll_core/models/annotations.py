"""A single source-backed annotation contract for final payroll cells."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class PayrollAnnotation:
    teacher_id: str
    teacher: str
    field_code: str
    display_label: str
    text: str
    source_type: str
    source_file: str
    source_sheet: str
    source_row: str
    source_field: str
    generated_from: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def normalize_annotations(items: Iterable[Mapping[str, Any]]) -> list[PayrollAnnotation]:
    """Validate, normalize and stably deduplicate annotations for one output cell."""
    output: list[PayrollAnnotation] = []
    seen: set[tuple[str, ...]] = set()
    for item in items:
        try:
            annotation = PayrollAnnotation(**{key: str(item.get(key) or "").strip() for key in PayrollAnnotation.__dataclass_fields__})
        except (AttributeError, TypeError):
            continue
        if not annotation.teacher or not annotation.field_code or not annotation.text:
            continue
        key = (
            annotation.teacher_id, annotation.field_code, annotation.text,
            annotation.source_type, annotation.source_file, annotation.source_sheet,
            annotation.source_row, annotation.source_field,
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(annotation)
    return sorted(output, key=lambda item: (
        item.field_code, item.source_type, item.source_file,
        item.source_sheet, item.source_row, item.text,
    ))


def comment_text(items: Iterable[Mapping[str, Any]]) -> str | None:
    """Render concise, human-readable source notes without IDs or hashes."""
    annotations = normalize_annotations(items)
    if not annotations:
        return None
    blocks = []
    for item in annotations:
        source_row = item.source_row
        if source_row and "," in source_row:
            source_row_label = f"涉及 {len([part for part in source_row.split(',') if part.strip()])} 条来源行"
        elif source_row:
            source_row_label = f"第 {source_row} 行"
        else:
            source_row_label = ""
        source = " · ".join(part for part in (
            item.source_file, item.source_sheet,
            source_row_label,
        ) if part)
        blocks.append(f"【{item.display_label or item.field_code}】\n{item.text}" + (f"\n来源：{source}" if source else ""))
    return "\n\n".join(blocks)
