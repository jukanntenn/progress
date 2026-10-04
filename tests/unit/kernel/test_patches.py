"""Patch algorithm + deferred ``_py`` expressions (PRFC phase 4a)."""

from __future__ import annotations

from typing import Any

import pytest

from progress.kernel.patches import (
    Patch,
    PyExpr,
    Row,
    apply_patches,
    dump_rows,
    evaluate_expression,
    load_py_nodes,
    parse_patch_document,
)


def _rows(*ids: str) -> list[Row]:
    return [Row(id=i, name=i) for i in ids]


def test_insert_appends_and_is_indexed_for_later_patches():
    inserted = Row(id="new-row", name="x")
    rows = apply_patches(
        _rows("a", "b"),
        [
            Patch(insert=[inserted]),
            Patch(target="new-row", disabled=True),
        ],
    )
    assert [r.id for r in rows] == ["a", "b", "new-row"]
    assert rows[2].disabled is True


def test_patch_replaces_whole_config_not_deep_merge():
    rows = apply_patches(
        [Row(id="a", config={"x": 1, "y": 2})],
        [Patch(target="a", config={"x": 9})],
    )
    assert rows[0].config == {"x": 9}


def test_unmatched_target_warns_and_skips(caplog):
    rows = apply_patches(_rows("a"), [Patch(target="missing", disabled=True)])
    assert [r.id for r in rows] == ["a"]
    assert rows[0].disabled is False


def test_duplicate_insert_id_skipped():
    rows = apply_patches(_rows("a"), [Patch(insert=[Row(id="a", name="dup")])])
    assert len(rows) == 1
    assert rows[0].name == "a"


def test_parse_patch_document_with_py_convention():
    doc = """
[[patch]]
target = "ai"
disabled = { _py = "not ctx.config.analysis.enabled" }

[[patch]]
target = "http"

[[patch.insert]]
id = "mine"
name = "thirdparty:mine"
inject = ["config"]

[patch.insert.config]
token = { _py = "ctx.config.token" }
"""
    patches = parse_patch_document(doc)
    assert len(patches) == 2
    assert isinstance(patches[0].disabled, PyExpr)
    assert patches[0].disabled.source == "not ctx.config.analysis.enabled"
    assert patches[1].target == "http"
    assert patches[1].insert[0].inject == ["config"]
    assert isinstance(patches[1].insert[0].config["token"], PyExpr)


def test_load_py_nodes_converts_nested():
    value = load_py_nodes({"a": {"_py": "1 + 1"}, "b": [{"_py": "ctx.x"}], "c": 3})
    assert isinstance(value["a"], PyExpr)
    assert isinstance(value["b"][0], PyExpr)
    assert value["c"] == 3


class _FakeCtx:
    def __init__(self, services: dict[str, Any]) -> None:
        self._services = services

    def get(self, name: str) -> Any:
        return self._services.get(name)


def test_expression_evaluates_with_ctx_mapping():
    ctx = _FakeCtx({"config": {"analysis": {"enabled": True}}})
    expr = PyExpr("bool(ctx.config['analysis']['enabled'])")
    assert evaluate_expression(expr, ctx, row_id="ai") is True


def test_expression_restricted_builtins_fail_loud():
    ctx = _FakeCtx({})
    with pytest.raises(RuntimeError, match="row 'x'"):
        evaluate_expression(PyExpr("__import__('os')"), ctx, row_id="x")
    with pytest.raises(RuntimeError, match="row 'x'"):
        evaluate_expression(PyExpr("open('/etc/passwd')"), ctx, row_id="x")


def test_missing_service_in_expression_raises_with_row_id():
    ctx = _FakeCtx({})
    with pytest.raises(RuntimeError, match="row 'y'"):
        evaluate_expression(PyExpr("ctx.config.x"), ctx, row_id="y")


def test_dump_prints_expressions_unevaluated():
    rows = [Row(id="ai", name="ai", disabled=PyExpr("not ctx.config.k"))]
    text = dump_rows(rows)
    assert "disabled=_py(not ctx.config.k)" in text
