from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypeGuard, TypeVar

R = TypeVar("R", covariant=True)


class Parseable(Protocol[R]):
    def parse(self, s: str) -> R: ...


ParserType = Callable[[str], R] | Parseable[R]


def is_parseable[R](parser: ParserType[R]) -> TypeGuard[Parseable[R]]:
    parse_attr = getattr(parser, "parse", None)
    return isinstance(parse_attr, Callable)
