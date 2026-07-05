from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

R = TypeVar("R", covariant=True)

ParserType = Callable[[str], R]
