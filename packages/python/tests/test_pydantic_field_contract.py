from __future__ import annotations

import ast
from pathlib import Path

import pytest

from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.rules._pydantic_field_contract import inert_annotation


def _is_inert(expression: str) -> bool:
    source = f"from typing import Annotated\nfrom pydantic import Field\nvalue: {expression}\n"
    context = PythonFileContext(Path("app/models.py"), source)
    assert context.tree is not None
    declaration = context.tree.body[-1]
    assert isinstance(declaration, ast.AnnAssign)
    return inert_annotation(declaration.annotation, context)


@pytest.mark.parametrize("member", ["str", "build_type()"])
def test_deep_annotations_preserve_eager_call_exclusion(member: str) -> None:
    expression = " | ".join(["str"] * 3000 + [member])
    assert _is_inert(expression) is (member == "str")


@pytest.mark.parametrize(
    ("metadata", "inert"),
    [
        ("Field(default_factory=lambda: deferred())", True),
        ("Field(default_factory=lambda data: deferred(data))", True),
        ("Field(default_factory=lambda value=eager(): value)", False),
        ("Field(default_factory=lambda value=1: value)", False),
        ("Field(default_factory=lambda *, value=eager(): value)", False),
        ("Field(default_factory=lambda *, value: value)", False),
        ("Field(default_factory=lambda: deferred(), title=eager())", False),
        ("Field(title=eager(), default_factory=lambda: deferred())", False),
        ("Field(*options)", False),
        ("Field(**options)", False),
    ],
)
def test_lambda_bodies_remain_deferred_without_ignoring_defaults_or_siblings(metadata: str, *, inert: bool) -> None:
    assert _is_inert(f"Annotated[str, {metadata}]") is inert
