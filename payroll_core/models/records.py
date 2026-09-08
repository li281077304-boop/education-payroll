from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ScheduleRecord:
    period: str
    teacher: str
    grade: str
    subject: str
    class_type: str
    attended: int
    lesson_status: str = ""
    student: str = ""
    lesson_time: str = ""
    source: str = ""


@dataclass(frozen=True)
class PayrollRecord:
    period: str
    teacher: str
    one_to_one: Optional[float] = None
    class_value: Optional[float] = None
    production: Optional[float] = None
    ae: Optional[float] = None
    af: Optional[float] = None
    av: Optional[float] = None
    source: str = ""


@dataclass(frozen=True)
class RenewalRecord:
    period: str
    teacher: str
    one_to_one_hours: Optional[float] = None
    class_hours: Optional[float] = None
    mentor_hours: Optional[float] = None
    recommendation_reward: Optional[float] = None
    source: str = ""


@dataclass(frozen=True)
class RefundRecord:
    period: str
    charge_teacher: str
    headcount_amount: Optional[float] = None
    performance_amount: Optional[float] = None
    source: str = ""

    @property
    def total_amount(self) -> Optional[float]:
        values = [v for v in (self.headcount_amount, self.performance_amount) if v is not None]
        return sum(values) if values else None
