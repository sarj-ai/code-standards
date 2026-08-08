"""SARJ082 — Prefer non-null list parameters when local use proves equivalence.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_non_nullable_collection.py
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, Severity, parse_or_none
from sarj_python_lint.rules._paths import is_generated, is_test_path, is_test_support_path


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


_UNION_NAMES = frozenset({"Optional", "Union"})
_NORMALIZATION_VALUE_COUNT = 2


class PreferNonNullableCollection(Rule):
    id: str = "prefer-non-nullable-collection"
    code: str = "SARJ082"
    description: str = (
        "A nullable list parameter should not expose two empty states when its only use immediately normalizes both."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_test_path(path) or is_test_support_path(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        diags: list[Diagnostic] = []
        for function in _eligible_functions(tree):
            if _is_override(function):
                continue
            diags.extend(
                Diagnostic(
                    path=path,
                    line=argument.lineno,
                    col=argument.col_offset + 1,
                    code=self.code,
                    message=(
                        f"`{argument.arg}` accepts `None` but the function uses it only as an empty list; "
                        "make the list required, or accept an immutable empty-default input such as "
                        "`Sequence[T] = ()` and materialize a list internally."
                    ),
                    severity=Severity.WARNING,
                )
                for argument in _equivalent_empty_parameters(function)
            )
        diags.sort(key=lambda diagnostic: (diagnostic.line, diagnostic.col))
        return diags


def _eligible_functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Return locally controlled module functions and constructors, excluding possibly inherited ordinary methods."""
    functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(statement)
        elif isinstance(statement, ast.ClassDef):
            functions.extend(
                member
                for member in statement.body
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name == "__init__"
            )
    return functions


def _equivalent_empty_parameters(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.arg]:
    matches: list[ast.arg] = []
    for argument, default in _parameters_with_defaults(function.args):
        if (
            argument.annotation is None
            or not _is_none(default)
            or not _is_nullable_list(argument.annotation)
            or not _is_only_empty_normalization(function, argument.arg)
        ):
            continue
        matches.append(argument)
    return matches


def _parameters_with_defaults(arguments: ast.arguments) -> list[tuple[ast.arg, ast.expr | None]]:
    positional = [*arguments.posonlyargs, *arguments.args]
    positional_defaults: list[ast.expr | None] = [None] * (len(positional) - len(arguments.defaults))
    positional_defaults.extend(arguments.defaults)
    return [
        *zip(positional, positional_defaults, strict=True),
        *zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True),
    ]


def _is_none(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _is_only_empty_normalization(function: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> bool:
    if _captured_by_nested_scope(function, name):
        return False
    loads: list[tuple[ast.Name, ast.AST | None]] = []
    for node, parent in _body_nodes(function):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id == name:
            loads.append((node, parent))
    if len(loads) == 1:
        node, parent = loads[0]
        if (
            isinstance(parent, ast.BoolOp)
            and isinstance(parent.op, ast.Or)
            and len(parent.values) == _NORMALIZATION_VALUE_COUNT
            and parent.values[0] is node
            and _is_empty_list(parent.values[1])
        ):
            return True
    return _starts_with_empty_normalization(function, name)


def _captured_by_nested_scope(function: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> bool:
    """Take a false negative when a closure also observes the nullable parameter."""
    for node in ast.walk(function):
        if node is function or not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if any(
            isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load) and child.id == name
            for child in ast.walk(node)
        ):
            return True
    return False


def _starts_with_empty_normalization(function: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> bool:
    """Recognize a first-statement guard or self-assignment that erases None."""
    statements = [statement for statement in function.body if not _is_docstring(statement)]
    if not statements:
        return False
    first = statements[0]
    match first:
        case ast.If(
            test=(
                ast.Compare(
                    left=ast.Name(id=subject),
                    ops=[ast.Is()],
                    comparators=[ast.Constant(value=None)],
                ) as comparison
            ),
            body=[ast.Assign(targets=[ast.Name(id=target)], value=value)],
            orelse=[],
        ) if subject == name and target == name and _is_empty_list(value):
            allowed_none_test: ast.Compare | None = comparison
        case ast.Assign(
            targets=[ast.Name(id=target)],
            value=ast.BoolOp(op=ast.Or(), values=[ast.Name(id=subject), value]),
        ) if target == name and subject == name and _is_empty_list(value):
            allowed_none_test = None
        case _:
            return False
    return not _observes_none(function, name, allowed=allowed_none_test)


def _is_docstring(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )


def _observes_none(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    name: str,
    *,
    allowed: ast.Compare | None,
) -> bool:
    """Report a second identity check that preserves None as a meaningful state."""
    for node, _parent in _body_nodes(function):
        if node is allowed or not isinstance(node, ast.Compare):
            continue
        if len(node.ops) != 1 or not isinstance(node.ops[0], (ast.Is, ast.IsNot)):
            continue
        if not isinstance(node.left, ast.Name) or node.left.id != name:
            continue
        if len(node.comparators) == 1 and _is_none(node.comparators[0]):
            return True
    return False


def _body_nodes(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Iterator[tuple[ast.AST, ast.AST | None]]:
    stack: list[tuple[ast.AST, ast.AST | None]] = [(statement, None) for statement in reversed(function.body)]
    while stack:
        node, parent = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        yield node, parent
        stack.extend((child, node) for child in reversed(list(ast.iter_child_nodes(node))))


def _is_empty_list(node: ast.expr) -> bool:
    return (isinstance(node, ast.List) and not node.elts) or (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "list"
        and not node.args
        and not node.keywords
    )


def _is_override(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in function.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Name) and target.id == "override":
            return True
        if isinstance(target, ast.Attribute) and target.attr == "override":
            return True
    return False


def _qualified_name(node: ast.expr) -> str:
    match node:
        case ast.Name(id=name):
            return name
        case ast.Attribute(value=value, attr=attr):
            parent = _qualified_name(value)
            return f"{parent}.{attr}" if parent else attr
        case ast.Subscript(value=value):
            return _qualified_name(value)
        case _:
            return ""


def _is_nullable_list(annotation: ast.expr) -> bool:
    members = _union_members(annotation)
    if members is None:
        return False
    non_none = [member for member in members if not _is_none_type(member)]
    return len(non_none) > 0 and len(non_none) < len(members) and all(_is_list_type(member) for member in non_none)


def _union_members(annotation: ast.expr) -> list[ast.expr] | None:
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        left = _union_members(annotation.left) or [annotation.left]
        right = _union_members(annotation.right) or [annotation.right]
        return [*left, *right]
    if isinstance(annotation, ast.Subscript) and _qualified_name(annotation.value).split(".")[-1] in _UNION_NAMES:
        if _qualified_name(annotation.value).endswith("Optional"):
            return [annotation.slice, ast.Constant(value=None)]
        if isinstance(annotation.slice, ast.Tuple):
            return list(annotation.slice.elts)
        return [annotation.slice]
    return None


def _is_none_type(node: ast.expr) -> bool:
    return (isinstance(node, ast.Constant) and node.value is None) or (isinstance(node, ast.Name) and node.id == "None")


def _is_list_type(node: ast.expr) -> bool:
    return isinstance(node, ast.Subscript) and _qualified_name(node.value).split(".")[-1] in {
        "List",
        "list",
    }
