"""Shared cron validator: the ``schedule_cron`` dialect."""

from __future__ import annotations

from pydantic import BaseModel, ValidationError
import pytest

from progress.utils.cron import CronExpression, is_valid_cron_expression, validate_cron_expression


class _Model(BaseModel):
    schedule_cron: CronExpression = ""


def test_empty_value_passes_and_means_inherit():
    assert validate_cron_expression("") == ""
    assert is_valid_cron_expression("") is False


@pytest.mark.parametrize(
    "expression",
    ["0 */4 * * *", "30 8,22 * * *", "*/5 * * * *", "0 0 * * 1", "0 6 * * *"],
)
def test_valid_five_field_expressions_pass(expression: str):
    assert validate_cron_expression(expression) == expression
    assert is_valid_cron_expression(expression) is True


@pytest.mark.parametrize(
    "expression",
    [
        "0 */4 * *",  # four fields
        "* * * * * *",  # six fields (seconds dialect)
        "0 */4 * * * *",  # six fields with step
        "60 * * * *",  # out-of-range minute
        "not a cron",
        "0 */4 * * * extra",
    ],
)
def test_invalid_expressions_raise(expression: str):
    with pytest.raises(ValueError, match="invalid cron expression"):
        validate_cron_expression(expression)
    assert is_valid_cron_expression(expression) is False


def test_annotated_type_validates_inside_a_model():
    assert _Model().schedule_cron == ""
    assert _Model(schedule_cron="0 */4 * * *").schedule_cron == "0 */4 * * *"
    with pytest.raises(ValidationError):
        _Model(schedule_cron="bogus")
