from __future__ import annotations

import ast

import pytest

from sarj_python_lint.rules._annotation_semantics import AnnotationSemantics, bit_or_members, scope_bound_names


def test_scope_collection_handles_deep_union_annotations() -> None:
    annotation = " | ".join(["str"] * 3001 + ["None"])
    tree = ast.parse(f"payload: {annotation}\n")
    assert scope_bound_names(tree.body) == {"payload"}


def test_scope_collection_preserves_nested_scope_exclusions() -> None:
    tree = ast.parse(
        "def function():\n    nested = 1\n"
        "async def asynchronous():\n    hidden = 1\n"
        "class Record:\n    field = 1\n"
        "factory = lambda: (deferred := 1)\n"
    )
    assert scope_bound_names(tree.body) == {"function", "asynchronous", "Record", "factory"}


def test_scope_collection_keeps_import_exception_and_match_bindings() -> None:
    tree = ast.parse(
        "import typing as types\nfrom pydantic import BaseModel as Model\n"
        "try:\n    pass\nexcept ValueError as caught:\n    local = 1\n"
        "match subject:\n    case {'key': bound, **rest}:\n        selected = 1\n"
        "    case [*items]:\n        pass\n"
    )
    assert scope_bound_names(tree.body) == {"types", "Model", "caught", "local", "bound", "rest", "selected", "items"}


def test_scope_collection_distinguishes_name_and_attribute_targets() -> None:
    tree = ast.parse("first, *remaining = values\nrecord.attribute = value\nlookup[key] = value\ndel removed\n")
    assert scope_bound_names(tree.body) == {"first", "remaining", "removed"}


def test_union_projection_preserves_operand_order_and_identity() -> None:
    expression = ast.parse("first | (second | third)", mode="eval").body
    assert isinstance(expression, ast.BinOp)
    assert isinstance(expression.right, ast.BinOp)
    expected = [expression.left, expression.right.left, expression.right.right]
    assert bit_or_members(expression) == expected


@pytest.mark.parametrize("source", ["A + B", "A & B", "A or B", "list[A | B]", "factory(A | B)"])
def test_union_projection_keeps_other_expressions_opaque(source: str) -> None:
    expression = ast.parse(source, mode="eval").body
    assert bit_or_members(expression) == [expression]


def test_union_projection_handles_deep_parsed_expression() -> None:
    expression = ast.parse(" | ".join(f"Type{index}" for index in range(1500)), mode="eval").body
    members = bit_or_members(expression)
    assert len(members) == 1500
    assert [member.id if isinstance(member, ast.Name) else None for member in members] == [
        f"Type{index}" for index in range(1500)
    ]


def test_annotation_members_handle_deep_parsed_union() -> None:
    expression = ast.parse(" | ".join(f"Type{index}" for index in range(1500)), mode="eval").body
    semantics = AnnotationSemantics.from_tree(ast.parse(""))
    members = semantics.transparent_members(expression)
    assert len(members) == 1500
    assert [member.id if isinstance(member, ast.Name) else None for member in members] == [
        f"Type{index}" for index in range(1500)
    ]


def test_annotation_union_keeps_alias_cycle_and_wrapper_policy() -> None:
    tree = ast.parse(
        "from typing import Annotated, Union\n"
        "type Recursive = int | Recursive\n"
        "type Wrapped = Annotated[Recursive | str, 'tag'] | Union[bytes, None]\n"
    )
    members = AnnotationSemantics.from_tree(tree).transparent_members(ast.parse("Wrapped", mode="eval").body)
    assert [ast.unparse(member) for member in members] == ["int", "str", "bytes", "None"]


def test_annotation_members_handle_long_alias_chain() -> None:
    aliases = [f"type Alias{index} = Alias{index + 1}" for index in range(1500)]
    source = "\n".join([*aliases, "type Alias1500 = int"])
    semantics = AnnotationSemantics.from_tree(ast.parse(source))
    members = semantics.transparent_members(ast.parse("Alias0", mode="eval").body)
    assert len(members) == 1
    assert isinstance(members[0], ast.Name)
    assert members[0].id == "int"


def test_annotation_alias_visits_are_local_to_each_branch() -> None:
    semantics = AnnotationSemantics.from_tree(ast.parse("type Recursive = int | Recursive\n"))
    members = semantics.transparent_members(ast.parse("Recursive | Recursive", mode="eval").body)
    assert len(members) == 2
    assert members[0] is members[1]


def test_annotation_empty_wrapper_stays_opaque() -> None:
    semantics = AnnotationSemantics.from_tree(ast.parse("from typing import Annotated\n"))
    expression = ast.parse("Annotated[()]", mode="eval").body
    assert semantics.transparent_members(expression) == (expression,)
