from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, NamedTuple, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    parse_or_none,
)
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path, is_test_support_path


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


_TYPING_SOURCES = frozenset({"typing", "typing_extensions"})
_BUILTIN_SOURCES = frozenset({"builtins"})
_NORMALIZATION_VALUE_COUNT = 2


class _ParameterDefault(NamedTuple):
    parameter: ast.arg
    default: ast.expr | None


@final
class PreferNonNullableCollection(Rule):
    id: str = "prefer-non-nullable-collection"
    code: str = "SARJ082"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Avoid nullable list parameters that are immediately collapsed to an empty list.",
        rationale=(
            "When an implementation immediately replaces both `None` and an empty list with the same fresh empty list, "
            "the callable contract exposes an extra input state that its body does not retain."
        ),
        remediation=(
            "After reviewing callers and list identity or mutation behavior, either require the list or accept "
            "`Sequence[T] = ()` and materialize a list internally. Removing explicit `None` acceptance is an API migration."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only undecorated module functions and constructors without a non-object base are checked for nullable list parameters defaulted to None.",
            "The warning requires a syntax-proven `items or []` normalization, either as the only read or as the first assignment; tests, generated code, ambiguous imports, guards, and conditional expressions are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="collapsed-nullable-list",
                title="Nullable list is immediately collapsed to an empty list",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/resolver.py",
                        "def resolve(candidates: list[str] | None = None) -> list[str]:\n    return candidates or []\n",
                    ),
                ),
                focus_path=PurePosixPath("app/resolver.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="immutable-empty-input",
                title="Immutable empty default keeps omission non-nullable",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/resolver.py",
                        "from collections.abc import Sequence\n\n"
                        "def resolve(candidates: Sequence[str] = ()) -> list[str]:\n"
                        "    return list(candidates)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/resolver.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_test_path(path) or is_test_support_path(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None or _has_wildcard_import(tree):
            return []

        imports = ImportIndex.from_tree(tree)
        diagnostics: list[Diagnostic] = []
        for function in _eligible_functions(tree, imports):
            if function.decorator_list:
                continue
            diagnostics.extend(
                Diagnostic(
                    path=path,
                    line=argument.lineno,
                    col=argument.col_offset + 1,
                    code=self.code,
                    message=(
                        f"`{argument.arg}` accepts `None` but is immediately collapsed to an empty list; after "
                        "reviewing callers and identity or mutation behavior, make it required or use an immutable "
                        "empty-default input such as `Sequence[T] = ()`."
                    ),
                    severity=Severity.WARNING,
                )
                for argument in _collapsed_empty_parameters(function, imports)
            )
        return sorted(diagnostics, key=lambda diagnostic: (diagnostic.line, diagnostic.col))


def _has_wildcard_import(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names) for node in ast.walk(tree)
    )


def _eligible_functions(tree: ast.Module, imports: ImportIndex) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(statement)
            continue
        if not isinstance(statement, ast.ClassDef) or _has_non_object_base(statement, imports):
            continue
        functions.extend(
            member
            for member in statement.body
            if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name == "__init__"
        )
    return functions


def _has_non_object_base(node: ast.ClassDef, imports: ImportIndex) -> bool:
    if not node.bases:
        return False
    return any(not _is_builtin_object(base, imports) for base in node.bases)


def _is_builtin_object(node: ast.expr, imports: ImportIndex) -> bool:
    if isinstance(node, ast.Name) and node.id == "object":
        return imports.builtin_is_unshadowed("object")
    return imports.resolves(node, sources=_BUILTIN_SOURCES, symbol="object")


def _collapsed_empty_parameters(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: ImportIndex,
) -> list[ast.arg]:
    return [
        argument
        for argument, default in _parameters_with_defaults(function.args)
        if argument.annotation is not None
        and _is_none(default)
        and _is_nullable_list(argument.annotation, imports)
        and _has_single_empty_collapse(function, argument.arg, imports)
    ]


def _parameters_with_defaults(arguments: ast.arguments) -> list[_ParameterDefault]:
    positional = [*arguments.posonlyargs, *arguments.args]
    positional_defaults: list[ast.expr | None] = [None] * (len(positional) - len(arguments.defaults))
    positional_defaults.extend(arguments.defaults)
    return [
        *map(_ParameterDefault, positional, positional_defaults, strict=True),
        *map(_ParameterDefault, arguments.kwonlyargs, arguments.kw_defaults, strict=True),
    ]


def _has_single_empty_collapse(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    name: str,
    imports: ImportIndex,
) -> bool:
    if _starts_with_self_collapse(function, name, imports):
        return True
    if _captured_by_nested_scope(function, name):
        return False
    loads = [
        (node, parent)
        for node, parent in _body_nodes(function)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id == name
    ]
    if len(loads) != 1:
        return False
    node, parent = loads[0]
    return (
        isinstance(parent, ast.BoolOp)
        and isinstance(parent.op, ast.Or)
        and len(parent.values) == _NORMALIZATION_VALUE_COUNT
        and parent.values[0] is node
        and _is_empty_list(parent.values[1], imports)
    )


def _starts_with_self_collapse(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    name: str,
    imports: ImportIndex,
) -> bool:
    statements = [statement for statement in function.body if not _is_docstring(statement)]
    if not statements:
        return False
    first = statements[0]
    return (
        isinstance(first, ast.Assign)
        and len(first.targets) == 1
        and isinstance(first.targets[0], ast.Name)
        and first.targets[0].id == name
        and isinstance(first.value, ast.BoolOp)
        and isinstance(first.value.op, ast.Or)
        and len(first.value.values) == _NORMALIZATION_VALUE_COUNT
        and isinstance(first.value.values[0], ast.Name)
        and first.value.values[0].id == name
        and _is_empty_list(first.value.values[1], imports)
    )


def _is_docstring(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )


def _captured_by_nested_scope(function: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> bool:
    for node in ast.walk(function):
        if node is function or not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if any(
            isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load) and child.id == name
            for child in ast.walk(node)
        ):
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


def _is_empty_list(node: ast.expr, imports: ImportIndex) -> bool:
    if isinstance(node, ast.List):
        return not node.elts
    if not isinstance(node, ast.Call) or node.args or node.keywords:
        return False
    if isinstance(node.func, ast.Name) and node.func.id == "list":
        return imports.builtin_is_unshadowed("list")
    return imports.resolves(node.func, sources=_BUILTIN_SOURCES, symbol="list")


def _is_none(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _is_nullable_list(annotation: ast.expr, imports: ImportIndex) -> bool:
    if (parsed := _stringized_annotation(annotation)) is not None:
        return _is_nullable_list(parsed, imports)
    if isinstance(annotation, ast.Subscript) and imports.resolves(
        annotation.value, sources=_TYPING_SOURCES, symbol="Annotated"
    ):
        if not isinstance(annotation.slice, ast.Tuple) or not annotation.slice.elts:
            return False
        return _is_nullable_list(annotation.slice.elts[0], imports)
    members = _union_members(annotation, imports)
    if members is None:
        return False
    non_none = [member for member in members if not _is_none_type(member)]
    return (
        bool(non_none) and len(non_none) < len(members) and all(_is_list_type(member, imports) for member in non_none)
    )


def _union_members(annotation: ast.expr, imports: ImportIndex) -> list[ast.expr] | None:
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        left = _union_members(annotation.left, imports) or [annotation.left]
        right = _union_members(annotation.right, imports) or [annotation.right]
        return [*left, *right]
    if not isinstance(annotation, ast.Subscript):
        return None
    if imports.resolves(annotation.value, sources=_TYPING_SOURCES, symbol="Optional"):
        return [annotation.slice, ast.Constant(value=None)]
    if not imports.resolves(annotation.value, sources=_TYPING_SOURCES, symbol="Union"):
        return None
    if isinstance(annotation.slice, ast.Tuple):
        return list(annotation.slice.elts)
    return [annotation.slice]


def _is_none_type(node: ast.expr) -> bool:
    return (isinstance(node, ast.Constant) and node.value is None) or (isinstance(node, ast.Name) and node.id == "None")


def _is_list_type(node: ast.expr, imports: ImportIndex) -> bool:
    if not isinstance(node, ast.Subscript):
        return False
    target = node.value
    if isinstance(target, ast.Name) and target.id == "list":
        return imports.builtin_is_unshadowed("list")
    return imports.resolves(target, sources=_BUILTIN_SOURCES, symbol="list") or imports.resolves(
        target, sources=_TYPING_SOURCES, symbol="List"
    )


def _stringized_annotation(annotation: ast.expr) -> ast.expr | None:
    if not isinstance(annotation, ast.Constant) or not isinstance(annotation.value, str):
        return None
    try:
        return ast.parse(annotation.value, mode="eval").body
    except SyntaxError:
        return None
