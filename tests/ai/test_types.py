from __future__ import annotations

from progress.ai.types import is_parseable


class _UpperParser:
    def parse(self, s: str) -> str:
        return s.upper()


def test_is_parseable_with_parseable():
    assert is_parseable(_UpperParser())


def test_is_parseable_with_callable():
    assert not is_parseable(str.upper)


def test_parseable_protocol_parse():
    parser = _UpperParser()
    assert parser.parse("hello") == "HELLO"
