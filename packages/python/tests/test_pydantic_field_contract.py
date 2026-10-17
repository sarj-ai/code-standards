from __future__ import annotations

import ast
from pathlib import Path

import pytest

from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.rules._pydantic_field_contract import direct_models, inert_annotation


def _is_inert(expression: str) -> bool:
    source = f"from typing import Annotated\nfrom pydantic import Field\nvalue: {expression}\n"
    context = PythonFileContext(Path("app/models.py"), source)
    assert context.tree is not None
    declaration = context.tree.body[-1]
    assert isinstance(declaration, ast.AnnAssign)
    return inert_annotation(declaration.annotation, context)


@pytest.mark.parametrize("escaped", ["\\ud800", "list[\\udfff]"])
def test_unencodable_forward_annotations_abstain_without_poisoning_valid_types(escaped: str) -> None:
    assert not _is_inert(repr(escaped.encode().decode("unicode_escape")))
    assert _is_inert("'str'")
    assert _is_inert("'Annotated[str, Field(title=\"é\")]'")


def test_model_authority_abstains_when_a_native_function_exposes_its_namespace() -> None:
    model = "from pydantic import BaseModel\nclass Payload(BaseModel):\n    text: str\n"
    ordinary = PythonFileContext(Path("app/models.py"), f"repr('direct call')\n{model}")
    escaped = PythonFileContext(Path("app/models.py"), f"native = getattr(repr, '__self__')\n{model}")
    assert len(direct_models(ordinary)) == 1
    assert direct_models(escaped) == ()


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
