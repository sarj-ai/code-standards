from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, NamedTuple, override

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
from sarj_python_lint.rules._paths import is_generated, is_test_path, is_test_support_path


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


_UNION_NAMES = frozenset({"Optional", "Union"})
_NORMALIZATION_VALUE_COUNT = 2


class _ParameterDefault(NamedTuple):
    parameter: ast.arg
    default: ast.expr | None


class PreferNonNullableCollection(Rule):
    id: str = "prefer-non-nullable-collection"
    code: str = "SARJ082"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Avoid nullable list parameters when local use proves `None` and an empty list are equivalent.",
        rationale="Exposing two equivalent empty states expands the function contract without preserving meaningful information.",
        remediation="Require the list, or accept an immutable empty default such as `Sequence[T] = ()` and materialize a list internally.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only module functions and constructors with a nullable list defaulted to `None` are analyzed.",
            "Overrides, tests, generated code, nested captures, multiple reads, and uses that preserve `None` as a distinct state are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="equivalent-empty-list-states",
                title="Nullable list is immediately normalized",
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
                example_id="required-list-input",
                title="Required list has one empty state",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/resolver.py",
                        "def resolve(candidates: list[str]) -> list[str]:\n    return candidates\n",
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
        if tree is None:
            return []

        diags: list[Diagnostic] = []
        constructor_owners = {
            member: statement
            for statement in tree.body
            if isinstance(statement, ast.ClassDef)
            for member in statement.body
            if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name == "__init__"
        }
        for function in _eligible_functions(tree):
            if _is_override(function):
                continue
            owner = constructor_owners.get(function)
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
                    severity=Severity.ERROR,
                )
                for argument in _equivalent_empty_parameters(function)
                if owner is None or not _forwards_inherited_constructor_parameter(owner, function, argument.arg)
            )
        diags.sort(key=lambda diagnostic: (diagnostic.line, diagnostic.col))
        return diags


def _eligible_functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
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


def _parameters_with_defaults(arguments: ast.arguments) -> list[_ParameterDefault]:
    positional = [*arguments.posonlyargs, *arguments.args]
    positional_defaults: list[ast.expr | None] = [None] * (len(positional) - len(arguments.defaults))
    positional_defaults.extend(arguments.defaults)
    return [
        *map(_ParameterDefault, positional, positional_defaults, strict=True),
        *map(_ParameterDefault, arguments.kwonlyargs, arguments.kw_defaults, strict=True),
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
        case ast.Assign(targets=[ast.Name(id=target)], value=ast.IfExp() as conditional) if target == name:
            if (comparison := _empty_normalizing_conditional(conditional, name)) is None:
                return False
            allowed_none_test = comparison
        case _:
            return False
    return not _observes_none(function, name, allowed=allowed_none_test)


def _empty_normalizing_conditional(conditional: ast.IfExp, name: str) -> ast.Compare | None:
    match conditional:
        case ast.IfExp(
            test=(
                ast.Compare(
                    left=ast.Name(id=subject),
                    ops=[ast.Is()],
                    comparators=[ast.Constant(value=None)],
                ) as comparison
            ),
            body=empty,
            orelse=ast.Name(id=fallback),
        ) if subject == name and fallback == name and _is_empty_list(empty):
            return comparison
        case ast.IfExp(
            test=(
                ast.Compare(
                    left=ast.Name(id=subject),
                    ops=[ast.IsNot()],
                    comparators=[ast.Constant(value=None)],
                ) as comparison
            ),
            body=ast.Name(id=present),
            orelse=empty,
        ) if subject == name and present == name and _is_empty_list(empty):
            return comparison
        case _:
            return None


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


def _forwards_inherited_constructor_parameter(
    owner: ast.ClassDef,
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    name: str,
) -> bool:
    if not any(_qualified_name(base).split(".")[-1] != "object" for base in owner.bases):
        return False
    for call in (node for node in ast.walk(function) if isinstance(node, ast.Call)):
        match call.func:
            case ast.Attribute(value=ast.Call(func=ast.Name(id="super")), attr="__init__"):
                values = [*call.args, *(keyword.value for keyword in call.keywords)]
                if any(
                    isinstance(descendant, ast.Name) and isinstance(descendant.ctx, ast.Load) and descendant.id == name
                    for value in values
                    for descendant in ast.walk(value)
                ):
                    return True
            case _:
                continue
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
