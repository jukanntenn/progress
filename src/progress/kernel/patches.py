"""Composition as data: rows, TOML patches, deferred ``_py`` expressions.

The patch algorithm ports cordis's ``applyEntryPatches`` semantics: inserts
are appended and indexed immediately (later patches in the same list may
target inserted rows); non-insert patches locate the row by ``id`` and
replace whole fields (config is replaced, never deep-merged); an unmatched
id warns and skips.

Deferred expressions ride the ``_py`` inline-table convention
(``disabled = { _py = "not ctx.config.analysis.enabled" }``) — a deliberate
deviation from the reference's YAML ``!!js`` tag with identical evaluation
semantics: evaluated only after the row's injections activate,
``disabled`` re-evaluated at every mount decision, dumped unevaluated.
The evaluator is a restricted eval (empty builtins plus a whitelist)
failing loud with the row id.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import logging
from typing import TYPE_CHECKING, Any, override

import tomlkit

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger("progress.kernel.patches")

SAFE_BUILTINS = {"len": len, "min": min, "max": max, "bool": bool, "str": str, "int": int, "float": float}


class PyExpr:  # noqa: PLW1641
    """A deferred expression node; printed unevaluated by dump."""

    __slots__ = ("source",)

    def __init__(self, source: str) -> None:
        self.source = source

    @override
    def __repr__(self) -> str:
        return f"_py({self.source!r})"

    @override
    def __eq__(self, other: object) -> bool:
        return isinstance(other, PyExpr) and other.source == self.source


@dataclass
class Row:
    """One composition row as data (structural only; business config is DB)."""

    id: str
    plugin: Any = None
    name: str = ""
    config: dict[str, Any] = field(default_factory=dict)
    inject: list[str] = field(default_factory=list)
    disabled: bool | PyExpr = False

    def describe(self) -> str:
        disabled = "true" if self.disabled is True else (f"_py({self.disabled.source})" if self.disabled else "false")
        injects = ",".join(self.inject) or "-"
        return f"{self.id:<22} name={self.name or '-':<20} inject=[{injects}] disabled={disabled}"


def load_py_nodes(value: Any) -> Any:
    """Recursively convert ``{_py: expr}`` inline tables into :class:`PyExpr`."""
    if isinstance(value, dict):
        if set(value.keys()) == {"_py"} and isinstance(value["_py"], str):
            return PyExpr(value["_py"])
        return {k: load_py_nodes(v) for k, v in value.items()}
    if isinstance(value, list):
        return [load_py_nodes(v) for v in value]
    return value


@dataclass
class Patch:
    """One patch instruction: insert rows, or replace fields of one row."""

    target: str | None = None
    insert: list[Row] = field(default_factory=list)
    disabled: bool | PyExpr | None = None
    config: dict[str, Any] | None = None
    name: str | None = None


def apply_patches(rows: list[Row], patches: list[Patch]) -> list[Row]:
    """Port of the reference patch algorithm (insert indexed; replace by id)."""
    result = list(rows)
    known_ids = {row.id for row in result}
    for patch in patches:
        if patch.insert:
            for row in patch.insert:
                if row.id in known_ids:
                    logger.warning("patch inserts duplicate row id %r; skipping", row.id)
                    continue
                result.append(row)
                known_ids.add(row.id)
            continue
        if patch.target is None:
            continue
        index = next((i for i, r in enumerate(result) if r.id == patch.target), None)
        if index is None:
            logger.warning("patch targets unknown row id %r; skipping", patch.target)
            continue
        current = result[index]
        updates: dict[str, Any] = {}
        if patch.name is not None:
            updates["name"] = patch.name
        if patch.disabled is not None:
            updates["disabled"] = patch.disabled
        if patch.config is not None:
            updates["config"] = patch.config
        result[index] = replace(current, **updates)
    return result


def parse_patch_document(text: str) -> list[Patch]:
    """Parse a TOML patch document.

    Shape::

        [[patch]]
        target = "ai"
        disabled = true

        [[patch]]
        target = "http"
        [patch.config]
        timeout = 30

        [[patch.insert]]
        id = "my-plugin"
        name = "thirdparty:my-plugin"
        [patch.insert.config]
        key = { _py = "ctx.config.x" }
    """
    document = tomlkit.parse(text)
    patches: list[Patch] = []
    for raw in document.get("patch", []):
        patch = Patch(
            target=raw.get("target"),
            disabled=load_py_nodes(raw.get("disabled")) if raw.get("disabled") is not None else None,
            name=raw.get("name"),
            config=load_py_nodes(dict(raw["config"])) if "config" in raw else None,
        )
        for inserted in raw.get("insert", []):
            row = Row(
                id=inserted["id"],
                name=inserted.get("name", ""),
                plugin=None,
                config=load_py_nodes(dict(inserted["config"])) if "config" in inserted else {},
                inject=list(inserted.get("inject", [])),
                disabled=load_py_nodes(inserted["disabled"]) if inserted.get("disabled") is not None else False,
            )
            patch.insert.append(row)
        patches.append(patch)
    return patches


def load_patch_file(path: Path) -> list[Patch]:
    return parse_patch_document(path.read_text(encoding="utf-8"))


class _CtxMapping:
    """Mapping/attribute view over a context for expression access."""

    def __init__(self, ctx: Any) -> None:
        self._ctx = ctx

    def __getitem__(self, key: str) -> Any:
        value = self._ctx.get(key)
        if value is None:
            raise KeyError(key)
        return value

    def __getattr__(self, key: str) -> Any:
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key) from None


def evaluate_expression(expr: PyExpr, ctx: Any, *, row_id: str) -> Any:
    """Restricted evaluation with the row's resolved services as the context."""
    environment: dict[str, Any] = {"__builtins__": {}, **SAFE_BUILTINS}
    try:
        return eval(expr.source, environment, {"ctx": _CtxMapping(ctx)})
    except Exception as e:
        raise RuntimeError(f"row {row_id!r}: _py expression {expr.source!r} failed: {e}") from e


def evaluate_row_config(row: Row, ctx: Any) -> dict[str, Any]:
    return {
        key: evaluate_expression(value, ctx, row_id=row.id) if isinstance(value, PyExpr) else value
        for key, value in row.config.items()
    }


def evaluate_disabled(row: Row, ctx: Any) -> bool:
    if row.disabled is False or row.disabled is None:
        return False
    if row.disabled is True:
        return True
    return bool(evaluate_expression(row.disabled, ctx, row_id=row.id))


def dump_rows(rows: list[Row]) -> str:
    """Render the effective tree, expressions unevaluated."""
    lines = ["# effective composition (expressions unevaluated)"]
    for row in rows:
        lines.append(row.describe())
        for key, value in row.config.items():
            lines.append(f"    config.{key} = {value!r}")
    return "\n".join(lines)


__all__ = [
    "Patch",
    "PyExpr",
    "Row",
    "apply_patches",
    "dump_rows",
    "evaluate_disabled",
    "evaluate_expression",
    "evaluate_row_config",
    "load_patch_file",
    "load_py_nodes",
    "parse_patch_document",
]
