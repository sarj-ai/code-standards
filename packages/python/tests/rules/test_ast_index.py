"""Direct tests for the shared node index every rule's traversal goes through."""

import ast

from sarj_python_lint.rules._ast_index import children, nodes, walk


_MODULE = '''\
"""Docstring."""

import os


class Store:
    prefix: str = "s"

    def get(self, key: str) -> str:
        if key:
            return self.prefix + key
        return ""


async def main(*, retries: int = 3) -> None:
    values = [x for x in range(retries) if x]
    match values:
        case [first, *rest]:
            print(first, rest)
        case _:
            pass
'''


def _tree() -> ast.Module:
    return ast.parse(_MODULE)


def test_walk_is_elementwise_identical_to_ast_walk() -> None:
    tree = _tree()
    assert [id(node) for node in walk(tree)] == [id(node) for node in ast.walk(tree)]


def test_children_is_elementwise_identical_to_iter_child_nodes() -> None:
    tree = _tree()
    for node in ast.walk(tree):
        assert [id(child) for child in children(node)] == [id(child) for child in ast.iter_child_nodes(node)]


def test_nodes_preserves_ast_walk_order_for_a_single_type() -> None:
    """The order invariant."""
    tree = _tree()
    expected = [n for n in ast.walk(tree) if isinstance(n, ast.Name)]
    assert [id(n) for n in nodes(tree, ast.Name)] == [id(n) for n in expected]


def test_nodes_preserves_ast_walk_order_across_several_types() -> None:
    tree = _tree()
    wanted = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    expected = [n for n in ast.walk(tree) if isinstance(n, wanted)]
    assert [id(n) for n in nodes(tree, *wanted)] == [id(n) for n in expected]


def test_nodes_matches_subclasses_not_exact_classes() -> None:
    """Buckets are keyed on exact class; a query for a BASE class must still resolve."""
    tree = _tree()
    expected = [n for n in ast.walk(tree) if isinstance(n, ast.stmt)]
    assert [id(n) for n in nodes(tree, ast.stmt)] == [id(n) for n in expected]
    assert len(expected) > 1


def test_nodes_for_the_universal_query_returns_the_whole_tree() -> None:
    tree = _tree()
    assert [id(n) for n in nodes(tree, ast.AST)] == [id(n) for n in ast.walk(tree)]


def test_a_type_absent_from_the_file_returns_nothing() -> None:
    assert nodes(ast.parse("x = 1\n"), ast.ClassDef) == []


def test_the_memo_slot_is_rebuilt_when_the_tree_changes() -> None:
    """One slot, keyed on tree identity -- so alternating trees must not alias."""
    first = ast.parse("class A:\n    pass\n")
    second = ast.parse("def b() -> None:\n    pass\n")
    assert len(nodes(first, ast.ClassDef)) == 1
    assert nodes(second, ast.ClassDef) == []
    assert len(nodes(second, ast.FunctionDef)) == 1
    assert nodes(first, ast.FunctionDef) == []
    assert len(nodes(first, ast.ClassDef)) == 1


def test_repeated_queries_of_the_same_types_agree() -> None:
    # The per-index query cache must not hand back a different answer the second
    # time, and must key on the type tuple rather than collapsing distinct ones.
    tree = _tree()
    assert nodes(tree, ast.Name) == nodes(tree, ast.Name)
    assert nodes(tree, ast.Name) != nodes(tree, ast.Attribute)


def test_walk_of_a_subtree_stays_inside_it() -> None:
    """`walk` exists for the containment question a whole-module index cannot answer."""
    tree = _tree()
    (klass,) = nodes(tree, ast.ClassDef)
    names = {n.id for n in walk(klass) if isinstance(n, ast.Name)}
    assert "self" in names
    assert "values" not in names
