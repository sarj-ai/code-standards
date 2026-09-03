from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, TypeGuard, final, override

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
    is_suppressed,
    parse_or_none,
)
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path, is_test_support_path


if TYPE_CHECKING:
    from pathlib import Path


_TYPING_SOURCES = frozenset({"typing", "typing_extensions"})
_COLLECTION_SOURCES = frozenset({"collections.abc", "typing"})
_BUILTIN_SOURCES = frozenset({"builtins"})
_UUID_SOURCES = frozenset({"uuid"})
_SQLALCHEMY_SOURCES = frozenset({"sqlalchemy.orm"})
_PYDANTIC_SOURCES = frozenset({"pydantic", "pydantic.fields", "pydantic.v1", "pydantic.v1.fields"})
_OPERATIONAL_IDS = frozenset(
    {
        "correlation_id",
        "correlation_ids",
        "operation_id",
        "operation_ids",
        "request_id",
        "request_ids",
        "span_id",
        "span_ids",
        "trace_id",
        "trace_ids",
        "unique_id",
        "unique_ids",
    }
)
_OPERATIONAL_PATH_PARTS = frozenset({"audit", "logger", "logging", "observability", "telemetry", "tracing"})
_OPERATIONAL_NAME_PARTS = frozenset({"context", "log", "logger", "logging", "telemetry", "trace", "tracing"})
_MIGRATION_PARTS = frozenset({"alembic", "migrations", "versions"})
_NON_PRODUCTION_PARTS = frozenset({"fixtures", "scripts", "test_fakes", "testing"})
_RAW_SCHEMA_SUFFIXES = ("Config", "Credentials", "Settings")
_MIN_SWAPPABLE_ROLES = 2
_SECOND_ARGUMENT = 1
_PAIR_ARITY = 2
_COLLECTION_WRAPPERS = frozenset(
    {
        "AbstractSet",
        "AsyncIterable",
        "AsyncIterator",
        "Collection",
        "FrozenSet",
        "Iterable",
        "Iterator",
        "List",
        "Sequence",
        "Set",
        "Tuple",
    }
)
_BUILTIN_COLLECTIONS = frozenset({"frozenset", "list", "set", "tuple"})


@dataclass(frozen=True, slots=True)
class _Carrier:
    shape: str
    raw: bool


@dataclass(frozen=True, slots=True)
class _IdRole:
    name: str
    annotation: ast.expr
    carrier: _Carrier


@dataclass(frozen=True, slots=True)
class _TypeFacts:
    raw_aliases: dict[str, str]
    nominal_aliases: dict[str, str]


@final
class PreferNominalIdTypes(Rule):
    id: str = "prefer-nominal-id-types"
    code: str = "SARJ093"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Public domain boundaries should distinguish swappable identifier roles with nominal types.",
        rationale=(
            "Two identifiers with the same primitive or container carrier can be exchanged without a type-checking error. "
            "Nominal types make those role mistakes visible while leaving unlike carriers alone."
        ),
        remediation=(
            "Use `typing.NewType` as the low-runtime-cost default and propagate it from the raw edge through the domain "
            "boundary. A nominal value object is also valid when runtime validation or behavior is required."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "The warning checks undecorated public module functions, public classes, their direct public methods, and constructors for at least two ID-shaped roles with the same proven carrier.",
            "Tests, generated code, migrations, support code, external adapters, operational context, raw schemas, SQLAlchemy Mapped fields, ambiguous imports, private boundaries, and unlike carrier shapes are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="swappable-primitive-id-roles",
                title="Two domain ID roles share the same primitive carrier",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/services/files.py",
                        "def move(file_id: str, parent_folder_id: str) -> None: ...\n",
                    ),
                ),
                focus_path=PurePosixPath("app/services/files.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="nominal-id-roles",
                title="NewType makes the two domain roles distinct",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/services/files.py",
                        "from typing import NewType\n\n"
                        "FileId = NewType('FileId', str)\n"
                        "FolderId = NewType('FolderId', str)\n\n"
                        "def move(file_id: FileId, parent_folder_id: FolderId) -> None: ...\n",
                    ),
                ),
                focus_path=PurePosixPath("app/services/files.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if _is_excluded_path(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None or _has_wildcard_import(tree):
            return []

        imports = ImportIndex.from_tree(tree)
        facts = _type_facts(tree, imports)
        source_lines = source.splitlines()
        class_role_names = {
            node: {role.name for role in _qualifying_roles(_boundary_roles(node, imports, facts))}
            for node in tree.body
            if isinstance(node, ast.ClassDef)
        }
        constructor_owners = {
            member: node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            for member in node.body
            if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name == "__init__"
        }

        diagnostics: list[Diagnostic] = []
        for node in _boundary_nodes(tree, imports):
            roles = _qualifying_roles(_boundary_roles(node, imports, facts))
            if not roles:
                continue
            owner = constructor_owners.get(node) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else None
            if owner is not None and class_role_names.get(owner):
                continue
            first_raw = next(role for role in roles if role.carrier.raw)
            if is_suppressed(source_lines, first_raw.annotation.lineno, self.code):
                continue
            names = ", ".join(f"`{role.name}`" for role in roles)
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=first_raw.annotation.lineno,
                    col=first_raw.annotation.col_offset + 1,
                    code=self.code,
                    message=(
                        f"{names} are swappable ID-shaped roles with the same carrier; introduce or reuse "
                        "`typing.NewType` or nominal value-object identifiers and propagate them through this boundary."
                    ),
                    severity=Severity.WARNING,
                )
            )
        return sorted(diagnostics, key=lambda diagnostic: (diagnostic.line, diagnostic.col))


def _is_excluded_path(path: Path) -> bool:
    lowered = {part.lower() for part in path.parts}
    path_tokens = {token for part in path.parts for token in part.lower().removesuffix(".py").split("_")}
    return (
        is_test_path(path)
        or is_test_support_path(path)
        or bool(lowered & _MIGRATION_PARTS)
        or bool(lowered & _NON_PRODUCTION_PARTS)
        or bool((lowered | path_tokens) & _OPERATIONAL_PATH_PARTS)
        or _is_external_adapter_path(path)
    )


def _has_wildcard_import(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names)
        for node in ast.walk(tree)
    )


def _boundary_nodes(
    tree: ast.Module,
    imports: ImportIndex,
) -> list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef]:
    result: list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef] = []
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _is_public_function(statement) and not _is_operational_function(statement):
                result.append(statement)
            continue
        if not isinstance(statement, ast.ClassDef) or statement.name.startswith("_"):
            continue
        if _name_parts(statement.name) & _OPERATIONAL_NAME_PARTS:
            continue
        if _is_raw_schema_class(statement, imports):
            continue
        result.append(statement)
        result.extend(
            member
            for member in statement.body
            if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
            and (member.name == "__init__" or _is_public_function(member))
            and not _is_operational_function(member)
        )
    return result


def _is_public_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return not node.name.startswith("_") and not node.decorator_list


def _is_operational_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return bool(_name_parts(node.name) & _OPERATIONAL_NAME_PARTS)


def _name_parts(name: str) -> set[str]:
    parts: list[str] = []
    current = ""
    for index, character in enumerate(name):
        if not character.isalnum():
            if current:
                parts.append(current.lower())
                current = ""
            continue
        starts_word = character.isupper() and bool(current) and (
            name[index - 1].islower() or (index + 1 < len(name) and name[index + 1].islower())
        )
        if starts_word:
            parts.append(current.lower())
            current = character
        else:
            current += character
    if current:
        parts.append(current.lower())
    return set(parts)


def _boundary_roles(
    node: ast.AST,
    imports: ImportIndex,
    facts: _TypeFacts,
) -> list[_IdRole]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if node.decorator_list:
            return []
        arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        if node.args.vararg is not None:
            arguments.append(node.args.vararg)
        return [
            role
            for argument in arguments
            if (role := _role(argument.arg, argument.annotation, imports, facts, allow_bare_id=True)) is not None
        ]
    if isinstance(node, ast.ClassDef):
        return [
            role
            for statement in node.body
            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
            and not _has_pydantic_wire_alias(statement, imports)
            if (role := _role(statement.target.id, statement.annotation, imports, facts, allow_bare_id=True)) is not None
        ]
    return []


def _role(
    name: str,
    annotation: ast.expr | None,
    imports: ImportIndex,
    facts: _TypeFacts,
    *,
    allow_bare_id: bool,
) -> _IdRole | None:
    if annotation is None or name in _OPERATIONAL_IDS:
        return None
    if not (name.endswith(("_id", "_ids")) or (allow_bare_id and name == "id")):
        return None
    carrier = _carrier(annotation, imports, facts)
    if carrier is None:
        return None
    return _IdRole(name=name, annotation=annotation, carrier=carrier)


def _qualifying_roles(roles: list[_IdRole]) -> list[_IdRole]:
    by_shape: dict[str, list[_IdRole]] = {}
    for role in roles:
        by_shape.setdefault(role.carrier.shape, []).append(role)
    qualifying_shapes = {
        shape
        for shape, same_shape in by_shape.items()
        if len(same_shape) >= _MIN_SWAPPABLE_ROLES and any(role.carrier.raw for role in same_shape)
    }
    return [role for role in roles if role.carrier.shape in qualifying_shapes]


def _has_pydantic_wire_alias(statement: ast.AnnAssign, imports: ImportIndex) -> bool:
    if _is_pydantic_wire_alias_call(statement.value, imports):
        return True
    annotation = statement.annotation
    if not isinstance(annotation, ast.Subscript):
        return False
    if not imports.resolves(annotation.value, sources=_TYPING_SOURCES, symbol="Annotated"):
        return False
    if not isinstance(annotation.slice, ast.Tuple):
        return False
    return any(_is_pydantic_wire_alias_call(metadata, imports) for metadata in annotation.slice.elts[1:])


def _is_pydantic_wire_alias_call(value: ast.expr | None, imports: ImportIndex) -> bool:
    return (
        isinstance(value, ast.Call)
        and imports.resolves(value.func, sources=_PYDANTIC_SOURCES, symbol="Field")
        and any(keyword.arg in {"alias", "serialization_alias", "validation_alias"} for keyword in value.keywords)
    )


def _type_facts(tree: ast.Module, imports: ImportIndex) -> _TypeFacts:
    raw_aliases: dict[str, str] = {}
    nominal_aliases: dict[str, str] = {}
    aliases: dict[str, ast.expr] = {}

    for statement in tree.body:
        target, value = _alias_assignment(statement)
        if target is None or value is None:
            continue
        if _is_new_type_call(value, imports):
            if len(value.args) >= _MIN_SWAPPABLE_ROLES:
                carrier = _carrier(value.args[_SECOND_ARGUMENT], imports, _TypeFacts(raw_aliases, nominal_aliases))
                if carrier is not None:
                    nominal_aliases[target] = carrier.shape
            continue
        aliases[target] = _type_alias_type_value(value, imports) or value

    for _round in range(len(aliases)):
        grew = False
        facts = _TypeFacts(raw_aliases, nominal_aliases)
        for name, value in aliases.items():
            if name in raw_aliases or name in nominal_aliases:
                continue
            carrier = _carrier(value, imports, facts)
            if carrier is None:
                continue
            destination = raw_aliases if carrier.raw else nominal_aliases
            destination[name] = carrier.shape
            grew = True
        if not grew:
            break
    return _TypeFacts(raw_aliases, nominal_aliases)


def _alias_assignment(statement: ast.stmt) -> tuple[str | None, ast.expr | None]:
    if isinstance(statement, ast.TypeAlias):
        return statement.name.id, statement.value
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
        return statement.targets[0].id, statement.value
    if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
        return statement.target.id, statement.value
    return None, None


def _is_new_type_call(value: ast.expr, imports: ImportIndex) -> TypeGuard[ast.Call]:
    return (
        isinstance(value, ast.Call)
        and imports.resolves(value.func, sources=_TYPING_SOURCES, symbol="NewType")
    )


def _type_alias_type_value(value: ast.expr, imports: ImportIndex) -> ast.expr | None:
    if not isinstance(value, ast.Call):
        return None
    if not imports.resolves(value.func, sources=_TYPING_SOURCES, symbol="TypeAliasType"):
        return None
    if len(value.args) >= _MIN_SWAPPABLE_ROLES:
        return value.args[_SECOND_ARGUMENT]
    return next((keyword.value for keyword in value.keywords if keyword.arg == "value"), None)


def _carrier(annotation: ast.expr, imports: ImportIndex, facts: _TypeFacts) -> _Carrier | None:
    if (parsed := _stringized_annotation(annotation)) is not None:
        return _carrier(parsed, imports, facts)
    if isinstance(annotation, ast.Name):
        if annotation.id in facts.raw_aliases:
            return _Carrier(facts.raw_aliases[annotation.id], raw=True)
        if annotation.id in facts.nominal_aliases:
            return _Carrier(facts.nominal_aliases[annotation.id], raw=False)
    if primitive := _primitive_carrier(annotation, imports):
        return _Carrier(primitive, raw=True)
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _union_carrier(_flatten_union(annotation), imports, facts)
    if not isinstance(annotation, ast.Subscript):
        return None

    target = annotation.value
    if imports.resolves(target, sources=_SQLALCHEMY_SOURCES, symbol="Mapped"):
        return None
    if imports.resolves(target, sources=_TYPING_SOURCES, symbol="Annotated"):
        if not isinstance(annotation.slice, ast.Tuple) or not annotation.slice.elts:
            return None
        return _carrier(annotation.slice.elts[0], imports, facts)
    if imports.resolves(target, sources=_TYPING_SOURCES, symbol="Optional"):
        return _carrier(annotation.slice, imports, facts)
    if imports.resolves(target, sources=_TYPING_SOURCES, symbol="Union"):
        members = list(annotation.slice.elts) if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
        return _union_carrier(members, imports, facts)

    wrapper = _collection_wrapper(target, imports)
    if wrapper is None:
        return None
    element = _collection_element(annotation.slice, wrapper)
    if element is None:
        return None
    nested = _carrier(element, imports, facts)
    if nested is None:
        return None
    return _Carrier(f"{wrapper}[{nested.shape}]", raw=nested.raw)


def _primitive_carrier(annotation: ast.expr, imports: ImportIndex) -> str | None:
    if isinstance(annotation, ast.Name) and annotation.id in {"int", "str"}:
        if imports.builtin_is_unshadowed(annotation.id):
            return annotation.id
        return None
    for symbol in ("int", "str"):
        if imports.resolves(annotation, sources=_BUILTIN_SOURCES, symbol=symbol):
            return symbol
    if imports.resolves(annotation, sources=_UUID_SOURCES, symbol="UUID"):
        return "UUID"
    return None


def _collection_wrapper(target: ast.expr, imports: ImportIndex) -> str | None:
    if isinstance(target, ast.Name) and target.id in _BUILTIN_COLLECTIONS:
        return target.id if imports.builtin_is_unshadowed(target.id) else None
    for symbol in _BUILTIN_COLLECTIONS:
        if imports.resolves(target, sources=_BUILTIN_SOURCES, symbol=symbol):
            return symbol
    for symbol in _COLLECTION_WRAPPERS:
        if imports.resolves(target, sources=_COLLECTION_SOURCES, symbol=symbol):
            return symbol.lower()
    return None


def _collection_element(slice_node: ast.expr, wrapper: str) -> ast.expr | None:
    if wrapper != "tuple":
        return slice_node
    if not isinstance(slice_node, ast.Tuple) or len(slice_node.elts) != _PAIR_ARITY:
        return None
    element, marker = slice_node.elts
    if isinstance(marker, ast.Constant) and marker.value is Ellipsis:
        return element
    return None


def _union_carrier(members: list[ast.expr], imports: ImportIndex, facts: _TypeFacts) -> _Carrier | None:
    carriers: list[_Carrier] = []
    for member in members:
        if _is_none(member):
            continue
        carrier = _carrier(member, imports, facts)
        if carrier is None:
            return None
        carriers.append(carrier)
    if not carriers:
        return None
    if len({carrier.shape for carrier in carriers}) != 1:
        return None
    return _Carrier(carriers[0].shape, raw=any(carrier.raw for carrier in carriers))


def _flatten_union(annotation: ast.expr) -> list[ast.expr]:
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return [*_flatten_union(annotation.left), *_flatten_union(annotation.right)]
    return [annotation]


def _is_none(annotation: ast.expr) -> bool:
    return (isinstance(annotation, ast.Constant) and annotation.value is None) or (
        isinstance(annotation, ast.Name) and annotation.id == "None"
    )


def _stringized_annotation(annotation: ast.expr) -> ast.expr | None:
    if not isinstance(annotation, ast.Constant) or not isinstance(annotation.value, str):
        return None
    try:
        return ast.parse(annotation.value, mode="eval").body
    except SyntaxError:
        return None


def _is_raw_schema_class(node: ast.ClassDef, imports: ImportIndex) -> bool:
    if node.name.endswith(_RAW_SCHEMA_SUFFIXES):
        return True
    return any(imports.resolves(base, sources=_TYPING_SOURCES, symbol="TypedDict") for base in node.bases)


def _is_external_adapter_path(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    return (
        "providers" in parts
        or ("adapters" in parts and ("models" in parts or path.name.lower() == "models.py"))
        or "integration" in parts
        or ("integrations" in parts and ("models" in parts or path.name.lower() == "models.py"))
    )
