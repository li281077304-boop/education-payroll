from __future__ import annotations

from typing import Callable

from .base import schedule_teachers, sum_class_value, sum_one_to_one


RULES: dict[str, Callable] = {
    "schedule_teachers": schedule_teachers,
    "sum_one_to_one": sum_one_to_one,
    "sum_class_value": sum_class_value,
}
