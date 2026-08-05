"""SARJ093 flags boundaries where multiple ID roles share primitive ID carrier types.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_nominal_id_types.py
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, is_suppressed, parse_or_none
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_TRANSPARENT_WRAPPERS = frozenset(
    {
        "AbstractSet",
        "AsyncIterable",
        "AsyncIterator",
        "Collection",
        "FrozenSet",
        "Iterable",
        "Iterator",
        "List",
        "Mapped",
        "Optional",
        "Sequence",
        "Set",
        "Tuple",
        "frozenset",
        "list",
        "set",
        "tuple",
    }
)
_UNION_WRAPPERS = frozenset({"Union"})
_MIN_ID_ROLES = 2
_VARIADIC_TUPLE_ARITY = 2
_TYPE_ALIAS_TYPE_MIN_ARGS = 2
_OPERATIONAL_IDS = frozenset(
    {
        "correlation_id",
        "operation_id",
        "request_id",
        "span_id",
        "trace_id",
        "unique_id",
    }
)
_MIGRATION_PARTS = frozenset({"alembic", "migrations", "versions"})
_NON_PRODUCTION_PARTS = frozenset({"fixtures", "scripts", "test_fakes", "testing"})
_RAW_SCHEMA_SUFFIXES = ("Config", "Credentials", "Settings")


@dataclass(frozen=True, slots=True)
class _IdRole:
    name: str
    annotation: ast.expr
    raw_primitive: bool


class PreferNominalIdTypes(Rule):
    id: str = "prefer-nominal-id-types"
    code: str = "SARJ093"
    description: str = (
        "A production boundary with multiple ID-shaped roles should use nominal ID types, not primitive carriers."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if (
            is_test_path(path)
            or is_generated(path, source)
            or any(part.lower() in _MIGRATION_PARTS for part in path.parts)
            or any(part.lower() in _NON_PRODUCTION_PARTS for part in path.parts)
            or _is_external_adapter_path(path)
        ):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        source_lines = source.splitlines()
        raw_aliases = _raw_alias_names(tree)
        nominal_aliases = _nominal_alias_names(tree)
        diagnostics: list[Diagnostic] = []
        exempt_schema_nodes = {
            descendant
            for candidate in ast.walk(tree)
            if isinstance(candidate, ast.ClassDef) and _is_raw_schema_class(candidate)
            for descendant in ast.walk(candidate)
            if descendant is not candidate
        }
        for node in _boundary_nodes(tree):
            if node in exempt_schema_nodes:
                continue
            roles = _boundary_roles(node, raw_aliases, nominal_aliases)
            raw = [role for role in roles if role.raw_primitive]
            if not raw or len({role.name for role in roles}) < _MIN_ID_ROLES:
                continue
            first = raw[0]
            if is_suppressed(source_lines, first.annotation.lineno, self.code):
                continue
            names = ", ".join(f"`{role.name}`" for role in roles)
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=first.annotation.lineno,
                    col=first.annotation.col_offset + 1,
                    code=self.code,
                    message=(
                        f"{names} are multiple ID-shaped roles at one boundary, but at least one uses a non-nominal ID carrier; "
                        "introduce or reuse `NewType` identifier types and propagate them through the boundary."
                    ),
                )
            )
        return sorted(diagnostics, key=lambda diagnostic: (diagnostic.line, diagnostic.col))


def _boundary_roles(
    node: ast.AST,
    raw_aliases: frozenset[str],
    nominal_aliases: frozenset[str],
) -> list[_IdRole]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if node.name.startswith("_") and node.name != "__init__":
            return []
        arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        if node.args.vararg is not None:
            arguments.append(node.args.vararg)
        if node.args.kwarg is not None:
            arguments.append(node.args.kwarg)
        return [
            role
            for argument in arguments
            if (
                role := _role(
                    argument.arg,
                    argument.annotation,
                    raw_aliases=raw_aliases,
                    nominal_aliases=nominal_aliases,
                )
            )
            is not None
        ]
    if isinstance(node, ast.ClassDef):
        if _is_raw_schema_class(node):
            return []
        return [
            role
            for statement in node.body
            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
            if (
                role := _role(
                    statement.target.id,
                    statement.annotation,
                    raw_aliases=raw_aliases,
                    nominal_aliases=nominal_aliases,
                    allow_bare_id=True,
                )
            )
            is not None
        ]
    return []


def _boundary_nodes(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef]:
    """Return module functions, classes, and direct methods—not nested implementation closures."""
    result: list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef] = []
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not _is_overload(statement):
                result.append(statement)
        elif isinstance(statement, ast.ClassDef):
            result.append(statement)
            result.extend(
                member
                for member in statement.body
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and not _is_overload(member)
            )
    return result


def _is_overload(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(_qualified_tail(decorator) == "overload" for decorator in node.decorator_list)


def _role(
    name: str,
    annotation: ast.expr | None,
    *,
    raw_aliases: frozenset[str],
    nominal_aliases: frozenset[str],
    allow_bare_id: bool = False,
) -> _IdRole | None:
    if annotation is None or name in _OPERATIONAL_IDS:
        return None
    if not (name.endswith(("_id", "_ids")) or (allow_bare_id and name == "id")):
        return None
    raw_primitive = _is_raw_primitive_id(annotation, raw_aliases, nominal_aliases)
    if not raw_primitive and not _is_nominal_id(annotation, raw_aliases, nominal_aliases):
        return None
    return _IdRole(name=name, annotation=annotation, raw_primitive=raw_primitive)


def _qualified_tail(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _is_raw_schema_class(node: ast.ClassDef) -> bool:
    return node.name.endswith(_RAW_SCHEMA_SUFFIXES) or any(_qualified_tail(base) == "Protocol" for base in node.bases)


def _is_external_adapter_path(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    return (
        "providers" in parts
        or ("adapters" in parts and ("models" in parts or path.name == "models.py"))
        or "integration" in parts
        or ("integrations" in parts and ("models" in parts or path.name == "models.py"))
    )


def _raw_alias_names(tree: ast.Module) -> frozenset[str]:
    aliases: dict[str, ast.expr] = {}
    for statement in tree.body:
        if isinstance(statement, ast.TypeAlias):
            aliases[statement.name.id] = statement.value
        elif (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            aliases[statement.targets[0].id] = _type_alias_type_value(statement.value) or statement.value
        elif (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.value is not None
        ):
            aliases[statement.target.id] = statement.value
    raw: set[str] = set()
    for _round in range(len(aliases)):
        grown = {
            name for name, value in aliases.items() if name not in raw and _is_raw_primitive_id(value, frozenset(raw))
        }
        if not grown:
            break
        raw |= grown
    return frozenset(raw)


def _type_alias_type_value(value: ast.expr) -> ast.expr | None:
    if not isinstance(value, ast.Call) or _qualified_tail(value.func) != "TypeAliasType":
        return None
    if len(value.args) >= _TYPE_ALIAS_TYPE_MIN_ARGS:
        return value.args[1]
    return next((keyword.value for keyword in value.keywords if keyword.arg == "value"), None)


def _nominal_alias_names(tree: ast.Module) -> frozenset[str]:
    new_type_calls = {"NewType"}
    for statement in tree.body:
        if isinstance(statement, ast.ImportFrom) and statement.module in {"typing", "typing_extensions"}:
            new_type_calls.update(alias.asname or alias.name for alias in statement.names if alias.name == "NewType")
    names: set[str] = set()
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target, value = statement.targets[0], statement.value
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            target, value = statement.target, statement.value
        else:
            continue
        if (
            isinstance(target, ast.Name)
            and isinstance(value, ast.Call)
            and _qualified_tail(value.func) in new_type_calls
        ):
            names.add(target.id)
    return frozenset(names)


def _stringized_annotation(annotation: ast.expr) -> ast.expr | None:
    if not isinstance(annotation, ast.Constant) or not isinstance(annotation.value, str):
        return None
    try:
        return ast.parse(annotation.value, mode="eval").body
    except SyntaxError:
        return None


def _is_raw_primitive_id(
    annotation: ast.expr,
    raw_aliases: frozenset[str] = frozenset(),
    nominal_aliases: frozenset[str] = frozenset(),
) -> bool:
    if (parsed := _stringized_annotation(annotation)) is not None:
        return _is_raw_primitive_id(parsed, raw_aliases, nominal_aliases)
    if isinstance(annotation, ast.Name):
        return annotation.id in {"UUID", "int", "str"} or annotation.id in raw_aliases
    if isinstance(annotation, ast.Attribute):
        return annotation.attr == "UUID"
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        members = _flatten_union(annotation)
        return any(_is_raw_primitive_id(member, raw_aliases, nominal_aliases) for member in members) and all(
            _is_raw_primitive_id(member, raw_aliases, nominal_aliases)
            or _is_nominal_id(member, raw_aliases, nominal_aliases)
            or _is_none(member)
            for member in members
        )
    if not isinstance(annotation, ast.Subscript):
        return False
    wrapper = _qualified_tail(annotation.value)
    if wrapper == "Annotated":
        return (
            isinstance(annotation.slice, ast.Tuple)
            and bool(annotation.slice.elts)
            and _is_raw_primitive_id(annotation.slice.elts[0], raw_aliases, nominal_aliases)
        )
    if wrapper in {"Tuple", "tuple"} and isinstance(annotation.slice, ast.Tuple):
        elements = annotation.slice.elts
        return (
            len(elements) == _VARIADIC_TUPLE_ARITY
            and isinstance(elements[1], ast.Constant)
            and elements[1].value is Ellipsis
            and _is_raw_primitive_id(elements[0], raw_aliases, nominal_aliases)
        )
    if wrapper in _TRANSPARENT_WRAPPERS:
        return _is_raw_primitive_id(annotation.slice, raw_aliases, nominal_aliases)
    if wrapper in _UNION_WRAPPERS:
        members = list(annotation.slice.elts) if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
        return any(_is_raw_primitive_id(member, raw_aliases, nominal_aliases) for member in members) and all(
            _is_raw_primitive_id(member, raw_aliases, nominal_aliases)
            or _is_nominal_id(member, raw_aliases, nominal_aliases)
            or _is_none(member)
            for member in members
        )
    return False


def _flatten_union(annotation: ast.expr) -> list[ast.expr]:
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return [*_flatten_union(annotation.left), *_flatten_union(annotation.right)]
    return [annotation]


def _is_none(annotation: ast.expr) -> bool:
    return (isinstance(annotation, ast.Constant) and annotation.value is None) or (
        isinstance(annotation, ast.Name) and annotation.id == "None"
    )


def _is_nominal_id(
    annotation: ast.expr,
    raw_aliases: frozenset[str] = frozenset(),
    nominal_aliases: frozenset[str] = frozenset(),
) -> bool:
    if (parsed := _stringized_annotation(annotation)) is not None:
        return _is_nominal_id(parsed, raw_aliases, nominal_aliases)
    if isinstance(annotation, (ast.Name, ast.Attribute)):
        tail = _qualified_tail(annotation)
        return (tail.endswith(("Id", "ID")) or tail in nominal_aliases) and tail not in raw_aliases
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        members = _flatten_union(annotation)
        return any(_is_nominal_id(member, raw_aliases, nominal_aliases) for member in members) and all(
            _is_nominal_id(member, raw_aliases, nominal_aliases) or _is_none(member) for member in members
        )
    if isinstance(annotation, ast.Subscript) and _qualified_tail(annotation.value) in _TRANSPARENT_WRAPPERS:
        if _qualified_tail(annotation.value) in {"Tuple", "tuple"} and isinstance(annotation.slice, ast.Tuple):
            elements = annotation.slice.elts
            return (
                len(elements) == _VARIADIC_TUPLE_ARITY
                and isinstance(elements[1], ast.Constant)
                and elements[1].value is Ellipsis
                and _is_nominal_id(elements[0], raw_aliases, nominal_aliases)
            )
        return _is_nominal_id(annotation.slice, raw_aliases, nominal_aliases)
    if (
        isinstance(annotation, ast.Subscript)
        and _qualified_tail(annotation.value) == "Annotated"
        and isinstance(annotation.slice, ast.Tuple)
    ):
        return bool(annotation.slice.elts) and _is_nominal_id(annotation.slice.elts[0], raw_aliases, nominal_aliases)
    if isinstance(annotation, ast.Subscript) and _qualified_tail(annotation.value) in _UNION_WRAPPERS:
        members = list(annotation.slice.elts) if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
        return any(_is_nominal_id(member, raw_aliases, nominal_aliases) for member in members) and all(
            _is_nominal_id(member, raw_aliases, nominal_aliases) or _is_none(member) for member in members
        )
    return False
