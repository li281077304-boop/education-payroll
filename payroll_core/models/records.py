from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional

from .evidence import SourceEvidence


@dataclass(frozen=True)
class ScheduleRecord:
    period: str
    teacher: str
    grade: str
    subject: str
    class_type: str
    attended: Optional[int]
    lesson_status: str = ""
    student: str = ""
    lesson_time: str = ""
    lesson_date: str = ""
    class_name: str = ""
    course_name: str = ""
    duration_text: str = ""
    source: str = ""
    provenance: Mapping[str, SourceEvidence] = field(default_factory=dict)


@dataclass(frozen=True)
class PayrollRecord:
    period: str
    teacher: str
    one_to_one: Optional[float] = None
    class_value: Optional[float] = None
    production: Optional[float] = None
    teaching_hours: Optional[float] = None
    teacher_level: str = ""
    ae: Optional[float] = None
    af: Optional[float] = None
    av: Optional[float] = None
    source: str = ""
    provenance: Mapping[str, SourceEvidence] = field(default_factory=dict)


@dataclass(frozen=True)
class RenewalRecord:
    period: str
    teacher: str
    one_to_one_hours: Optional[float] = None
    class_hours: Optional[float] = None
    mentor_hours: Optional[float] = None
    recommendation_reward: Optional[float] = None
    source: str = ""
    provenance: Mapping[str, SourceEvidence] = field(default_factory=dict)


@dataclass(frozen=True)
class RefundRecord:
    period: str
    charge_teacher: str
    headcount_amount: Optional[float] = None
    performance_amount: Optional[float] = None
    source: str = ""
    provenance: Mapping[str, SourceEvidence] = field(default_factory=dict)

    @property
    def total_amount(self) -> Optional[float]:
        values = [v for v in (self.headcount_amount, self.performance_amount) if v is not None]
        return sum(values) if values else None


@dataclass(frozen=True)
class PayrollCheckRecord:
    period: str
    teacher: str
    one_to_one_expected: Optional[float] = None
    one_to_one_actual: Optional[float] = None
    one_to_one_difference: Optional[float] = None
    class_expected: Optional[float] = None
    class_actual: Optional[float] = None
    class_difference: Optional[float] = None
    source: str = ""
    provenance: Mapping[str, SourceEvidence] = field(default_factory=dict)
