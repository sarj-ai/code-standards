import ast

import pytest

from sarj_python_lint.rules._ast_names import (
    dotted_name,
    dotted_parts,
    expression_root,
    root_name,
    terminal_name,
    unqualified_name,
)


@pytest.mark.parametrize(
    ("source", "root", "expression", "terminal", "parts"),
    [
        ("root", "root", "root", "root", ("root",)),
        ("root.item", "root", "root", "item", ("root", "item")),
        ("root[0].item", None, "root", "item", None),
        ("factory().item", None, None, "item", None),
        ("factory()", None, None, None, None),
        ("42", None, None, None, None),
    ],
)
def test_name_shapes_preserve_unknown_roots(
    source: str,
    root: str | None,
    expression: str | None,
    terminal: str | None,
    parts: tuple[str, ...] | None,
) -> None:
    node = ast.parse(source, mode="eval").body
    assert root_name(node) == root
    assert expression_root(node) == expression
    assert terminal_name(node) == terminal
    assert unqualified_name(node) == (terminal or "")
    assert dotted_parts(node) == parts
    assert dotted_name(node) == (".".join(parts) if parts is not None else None)


def test_dotted_names_handle_deep_attribute_chains_without_recursion() -> None:
    depth = 1500
    node: ast.expr = ast.Name(id="root")
    for _ in range(depth):
        node = ast.Attribute(value=node, attr="member", ctx=ast.Load())
    expected = ("root",) + ("member",) * depth
    assert dotted_parts(node) == expected
    assert dotted_name(node) == ".".join(expected)
