"""Cron expression validation shared by schedule-capable config models.

One validator owns the dialect everywhere a cron expression enters a pydantic
config model (the ``schedule_cron`` override field): an empty value means
"inherit the global schedule", a non-empty value must be a valid 5-field cron
expression — the dialect the in-process scheduler parses. Six-field (seconds)
forms are rejected so every schedule surface agrees with ``every(cron, fn)``.
"""

from __future__ import annotations

from typing import Annotated

from croniter import croniter
from pydantic import AfterValidator


def is_valid_cron_expression(expression: str) -> bool:
    parts = expression.split()
    return len(parts) == 5 and croniter.is_valid(expression)


def validate_cron_expression(value: str) -> str:
    if value and not is_valid_cron_expression(value):
        raise ValueError(
            f"invalid cron expression {value!r}: expected a 5-field expression like '0 */4 * * *', "
            "or empty to inherit the global schedule"
        )
    return value


CronExpression = Annotated[str, AfterValidator(validate_cron_expression)]


__all__ = ["CronExpression", "is_valid_cron_expression", "validate_cron_expression"]
