from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import PurePosixPath
import re
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
)
from sarj_python_lint.rules._ast_index import walk as walk_ast
from sarj_python_lint.rules._nominal_project import NominalSource


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._ast_index import NodeIndex
    from sarj_python_lint.rules._imports import ImportIndex


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
_RAW_SCHEMA_SUFFIXES = ("Config", "Credentials", "Settings")
_MIN_SWAPPABLE_ROLES = 2
_SECOND_ARGUMENT = 1
_PAIR_ARITY = 2
_MAX_ALIAS_DEPTH = 8
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
    value_roles: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class _ScopeFacts:
    sources: dict[str, NominalSource]
    resolved: dict[tuple[str, str | None], _TypeFacts]
    roles: dict[str, str]


@dataclass(frozen=True, slots=True)
class _BoundaryOwnership:
    classes: dict[ast.ClassDef, set[str]]
    original_classes: dict[ast.ClassDef, list[_IdRole]]
    constructors: dict[ast.FunctionDef | ast.AsyncFunctionDef, ast.ClassDef]
    original_constructor_owners: set[ast.ClassDef]

    def redundant(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, *, has_original: bool) -> bool:
        if isinstance(node, ast.ClassDef):
            return node in self.original_constructor_owners and not has_original
        owner = self.constructors.get(node)
        return (
            owner is not None
            and bool(self.classes.get(owner))
            and (bool(self.original_classes.get(owner)) or not has_original)
        )


@final
class PreferNominalIdTypes(Rule):
    id: str = "prefer-nominal-id-types"
    code: str = "SARJ093"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Python boundaries should distinguish swappable identifier roles with nominal types.",
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
            "The rule checks functions, methods, constructors, and classes for at least two ID-shaped roles with the same proven carrier. Existing coverage remains an error.",
            "Imported first-party carriers and non-ID roles backed by a unique matching NewType in the owning distribution or a declared local dependency are warnings. Ambiguous exports, conditional or relative imports, cycles, and unresolved ownership are skipped.",
            "Non-ID role discovery uses exact snake-case names and proven matching carriers; it does not infer brands from names alone. Dependency discovery respects declared workspace members and exclusions, and excludes optional and transitive dependencies.",
            "Generated code, migrations, external adapters, operational context, raw schemas, SQLAlchemy Mapped fields, ambiguous imports, and unlike carrier shapes are excluded.",
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

    def __init__(self) -> None:
        self._scope_cache: list[_ScopeFacts] = []

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        if _is_excluded_path(path) or context.generated:
            return []
        tree = context.tree
        if tree is None or _has_wildcard_import(tree, node_index=context.node_index):
            return []

        imports = context.imports
        original_facts = _type_facts(tree, imports)
        boundaries = _boundary_nodes(tree, imports)
        facts = (
            self._expanded_facts(context, tree, imports)
            if any(_can_expand(node, imports, original_facts) for node in boundaries)
            else original_facts
        )
        source_lines = context.source_lines
        class_role_names = {
            node: {role.name for role in _qualifying_roles(_boundary_roles(node, imports, facts))}
            for node in tree.body
            if isinstance(node, ast.ClassDef)
        }
        constructor_owners = _constructor_owners(tree)
        original_class_roles = {
            node: _qualifying_roles(_boundary_roles(node, imports, original_facts)) for node in class_role_names
        }
        original_constructor_owners = {
            owner
            for constructor, owner in constructor_owners.items()
            if _qualifying_roles(_boundary_roles(constructor, imports, original_facts))
        }

        ownership = _BoundaryOwnership(
            class_role_names, original_class_roles, constructor_owners, original_constructor_owners
        )
        diagnostics: list[Diagnostic] = []

        def collect_boundary_diagnostics() -> None:
            for node in boundaries:
                roles = _qualifying_roles(_boundary_roles(node, imports, facts))
                if not roles:
                    continue
                old_roles = _qualifying_roles(_boundary_roles(node, imports, original_facts))
                if ownership.redundant(node, has_original=bool(old_roles)):
                    continue
                diagnostic_roles = old_roles or roles
                first_raw = next(role for role in diagnostic_roles if role.carrier.raw)
                if is_suppressed(source_lines, first_raw.annotation.lineno, self.code):
                    continue
                diagnostics.append(
                    Diagnostic(
                        path=path,
                        line=first_raw.annotation.lineno,
                        col=first_raw.annotation.col_offset + 1,
                        code=self.code,
                        message=_boundary_message(diagnostic_roles, established=bool(old_roles)),
                        severity=Severity.ERROR if old_roles else Severity.WARNING,
                    )
                )

        collect_boundary_diagnostics()
        return sorted(diagnostics, key=lambda diagnostic: (diagnostic.line, diagnostic.col))

    def _expanded_facts(self, context: PythonFileContext, tree: ast.Module, imports: ImportIndex) -> _TypeFacts:
        sources = (
            context.session.nominal_project.sources(context.path, context.session.first_party)
            if context.path.is_file()
            else {}
        )
        if not sources:
            sources = {"__local__": NominalSource(context.path, context.source)}
        cached = next((entry for entry in self._scope_cache if entry.sources is sources), None)
        if cached is None:
            resolved: dict[tuple[str, str | None], _TypeFacts] = {}
            for module, source in sources.items():
                if _canonical_source(source):
                    _module_facts(module, sources, resolved, (), None)
            roles = _canonical_roles(sources, resolved)
            cached = _ScopeFacts(sources, resolved, roles)
            self._scope_cache = [*self._scope_cache[-7:], cached]
        seed = _imported_facts(imports, sources, cached.resolved, (), tree, include_annotations=True)
        facts = _type_facts(tree, imports, seed)
        return _TypeFacts(facts.raw_aliases, facts.nominal_aliases, cached.roles)


def _is_excluded_path(path: Path) -> bool:
    lowered = {part.lower() for part in path.parts}
    path_tokens = {token for part in path.parts for token in part.lower().removesuffix(".py").split("_")}
    return (
        bool(lowered & _MIGRATION_PARTS)
        or bool((lowered | path_tokens) & _OPERATIONAL_PATH_PARTS)
        or _is_external_adapter_path(path)
    )


def _has_wildcard_import(tree: ast.Module, *, node_index: NodeIndex | None = None) -> bool:
    return any(
        isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names)
        for node in walk_ast(tree, index=node_index)
    )


def _boundary_nodes(
    tree: ast.Module,
    imports: ImportIndex,
) -> list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef]:
    result: list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef] = []
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not _is_operational_function(statement):
                result.append(statement)
            continue
        if not isinstance(statement, ast.ClassDef):
            continue
        if _name_parts(statement.name) & _OPERATIONAL_NAME_PARTS:
            continue
        if _is_raw_schema_class(statement, imports):
            continue
        result.append(statement)
        result.extend(_boundary_methods(statement))
    return result


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
        starts_word = (
            character.isupper()
            and bool(current)
            and (name[index - 1].islower() or (index + 1 < len(name) and name[index + 1].islower()))
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
        arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        if node.args.vararg is not None:
            arguments.append(node.args.vararg)
        return [
            role
            for argument in arguments
            if (role := _role(argument.arg, argument.annotation, imports, facts, allow_bare_id=True)) is not None
        ]
    if isinstance(node, ast.ClassDef):
        return _class_id_roles(node, imports, facts)
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
    is_id = name.endswith(("_id", "_ids")) or (allow_bare_id and name == "id")
    carrier = _carrier(annotation, imports, facts)
    if carrier is None:
        return None
    if not is_id and (facts.value_roles is None or facts.value_roles.get(name) != carrier.shape):
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


def _class_id_roles(node: ast.ClassDef, imports: ImportIndex, facts: _TypeFacts) -> list[_IdRole]:
    return [
        role
        for statement in node.body
        if isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
        and not _has_pydantic_wire_alias(statement, imports)
        if (role := _role(statement.target.id, statement.annotation, imports, facts, allow_bare_id=True)) is not None
    ]


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


def _type_facts(tree: ast.Module, imports: ImportIndex, seed: _TypeFacts | None = None) -> _TypeFacts:
    raw_aliases: dict[str, str] = dict(seed.raw_aliases) if seed is not None else {}
    nominal_aliases: dict[str, str] = dict(seed.nominal_aliases) if seed is not None else {}
    aliases: dict[str, ast.expr] = {}

    _collect_type_aliases(tree, imports, raw_aliases, nominal_aliases, aliases)
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


def _collect_type_aliases(
    tree: ast.Module,
    imports: ImportIndex,
    raw_aliases: dict[str, str],
    nominal_aliases: dict[str, str],
    aliases: dict[str, ast.expr],
) -> None:
    for statement in tree.body:
        assignment = _alias_assignment(statement)
        if assignment is None:
            continue
        target = assignment.target
        value = assignment.value
        if _is_new_type_call(value, imports):
            if len(value.args) >= _MIN_SWAPPABLE_ROLES:
                carrier = _carrier(value.args[_SECOND_ARGUMENT], imports, _TypeFacts(raw_aliases, nominal_aliases))
                if carrier is not None:
                    nominal_aliases[target] = carrier.shape
            continue
        aliases[target] = _type_alias_type_value(value, imports) or value


@dataclass(frozen=True, slots=True)
class _AliasAssignment:
    target: str
    value: ast.expr


def _alias_assignment(statement: ast.stmt) -> _AliasAssignment | None:
    if isinstance(statement, ast.TypeAlias):
        return _AliasAssignment(target=statement.name.id, value=statement.value)
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
        return _AliasAssignment(target=statement.targets[0].id, value=statement.value)
    if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name) and statement.value is not None:
        return _AliasAssignment(target=statement.target.id, value=statement.value)
    return None


def _is_new_type_call(value: ast.expr, imports: ImportIndex) -> TypeGuard[ast.Call]:
    return isinstance(value, ast.Call) and imports.resolves(value.func, sources=_TYPING_SOURCES, symbol="NewType")


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
    if isinstance(annotation, (ast.Name, ast.Attribute)):
        name = ast.unparse(annotation)
        if name in facts.raw_aliases:
            return _Carrier(facts.raw_aliases[name], raw=True)
        if name in facts.nominal_aliases:
            return _Carrier(facts.nominal_aliases[name], raw=False)
    if primitive := _primitive_carrier(annotation, imports):
        return _Carrier(primitive, raw=True)
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _union_carrier(_flatten_union(annotation), imports, facts)
    if not isinstance(annotation, ast.Subscript):
        return None

    return _subscript_carrier(annotation, imports, facts)


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


def _subscript_carrier(annotation: ast.Subscript, imports: ImportIndex, facts: _TypeFacts) -> _Carrier | None:
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


def _constructor_owners(tree: ast.Module) -> dict[ast.FunctionDef | ast.AsyncFunctionDef, ast.ClassDef]:
    return {
        member: node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        for member in node.body
        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name == "__init__"
    }


def _boundary_methods(statement: ast.ClassDef) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        member
        for member in statement.body
        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and not _is_operational_function(member)
    ]


def _module_facts(
    module: str,
    sources: dict[str, NominalSource],
    resolved: dict[tuple[str, str | None], _TypeFacts],
    visiting: tuple[str, ...],
    requested: str | None,
) -> _TypeFacts:
    if module in visiting or len(visiting) >= _MAX_ALIAS_DEPTH or module not in sources:
        return _TypeFacts({}, {})
    key = (module, requested)
    if key in resolved:
        return resolved[key]
    local = resolved.get((module, None))
    if (
        local is not None
        and requested is not None
        and (requested in local.raw_aliases or requested in local.nominal_aliases)
    ):
        return local
    source = sources[module]
    if source.tree is None:
        return _TypeFacts({}, {})
    if requested is not None and any(
        isinstance(statement, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and statement.name == requested
        for statement in source.tree.body
    ):
        resolved[key] = _TypeFacts({}, {})
        return resolved[key]
    seed = _imported_facts(source.imports, sources, resolved, (*visiting, module), source.tree, requested=requested)
    facts = _type_facts(source.tree, source.imports, seed)
    result = _unambiguous_exports(source.tree, source.imports, facts)
    resolved[key] = result
    return result


def _unambiguous_exports(tree: ast.Module, imports: ImportIndex, facts: _TypeFacts) -> _TypeFacts:
    assignments: dict[str, list[_AliasAssignment]] = {}
    for statement in tree.body:
        if (assignment := _alias_assignment(statement)) is not None:
            assignments.setdefault(assignment.target, []).append(assignment)
    # Imports are re-exports only when their binding is unambiguous; local
    # aliases must have exactly one top-level assignment and no other writes.
    unique = {name for name, values in assignments.items() if len(values) == 1 and _binding_count(tree, name) == 1}
    allowed = unique | set(imports.bindings)
    return _TypeFacts(
        {name: shape for name, shape in facts.raw_aliases.items() if name in allowed},
        {name: shape for name, shape in facts.nominal_aliases.items() if name in allowed},
    )


def _binding_count(tree: ast.Module, name: str) -> int:
    return sum(
        1
        for node in walk_ast(tree)
        if (isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)) and node.id == name)
        or (isinstance(node, ast.arg) and node.arg == name)
        or (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name)
        or (isinstance(node, ast.alias) and (node.asname or node.name.partition(".")[0]) == name)
    )


def _imported_facts(
    imports: ImportIndex,
    sources: dict[str, NominalSource],
    resolved: dict[tuple[str, str | None], _TypeFacts],
    visiting: tuple[str, ...],
    tree: ast.Module,
    *,
    requested: str | None = None,
    include_annotations: bool = False,
) -> _TypeFacts:
    raw: dict[str, str] = {}
    nominal: dict[str, str] = {}
    needed = _needed_carrier_names(tree, imports, include_annotations=include_annotations)
    if requested is not None:
        needed.add(requested)
    mutated = {
        ast.unparse(node).partition(".")[0]
        for node in walk_ast(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del))
    }
    for local, binding in imports.bindings.items():
        if local in mutated:
            continue
        targets = _requested_imports(local, binding.symbol, needed)
        for symbol, alias in targets.items():
            facts = _module_facts(binding.module, sources, resolved, visiting, symbol)
            if symbol in facts.raw_aliases:
                raw[alias] = facts.raw_aliases[symbol]
            if symbol in facts.nominal_aliases:
                nominal[alias] = facts.nominal_aliases[symbol]
    return _TypeFacts(raw, nominal)


def _requested_imports(local: str, symbol: str | None, needed: set[str]) -> dict[str, str]:
    if symbol is not None:
        return {symbol: local} if local in needed else {}
    return {name.removeprefix(f"{local}."): name for name in needed if name.startswith(f"{local}.")}


def _needed_carrier_names(tree: ast.Module, imports: ImportIndex, *, include_annotations: bool) -> set[str]:
    expressions: list[ast.expr] = []
    for statement in tree.body:
        assignment = _alias_assignment(statement)
        if assignment is None:
            continue
        value = assignment.value
        if _is_new_type_call(value, imports) and len(value.args) >= _MIN_SWAPPABLE_ROLES:
            expressions.append(value.args[_SECOND_ARGUMENT])
        elif (alias_value := _type_alias_type_value(value, imports)) is not None:
            expressions.append(alias_value)
        elif not isinstance(value, ast.Call):
            expressions.append(value)
    if include_annotations:
        expressions.extend(_annotations(tree))
    names: set[str] = set()
    for expression in expressions:
        parsed = _stringized_annotation(expression) or expression
        names.update(ast.unparse(node) for node in walk_ast(parsed) if isinstance(node, (ast.Name, ast.Attribute)))
    return names


def _annotations(tree: ast.Module) -> list[ast.expr]:
    return [
        node.annotation
        for node in walk_ast(tree)
        if isinstance(node, (ast.arg, ast.AnnAssign)) and node.annotation is not None
    ]


def _can_expand(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, imports: ImportIndex, facts: _TypeFacts
) -> bool:
    if _qualifying_roles(_boundary_roles(node, imports, facts)):
        return False
    annotations = _boundary_annotations(node)
    carriers = [carrier for annotation in annotations if (carrier := _carrier(annotation, imports, facts)) is not None]
    if len(carriers) < len(annotations):
        return len(annotations) >= _MIN_SWAPPABLE_ROLES
    return any(
        carrier.raw and sum(other.shape == carrier.shape for other in carriers) >= _MIN_SWAPPABLE_ROLES
        for carrier in carriers
    )


def _boundary_annotations(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> list[ast.expr]:
    if isinstance(node, ast.ClassDef):
        annotations = [member.annotation for member in node.body if isinstance(member, ast.AnnAssign)]
    else:
        arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        if node.args.vararg is not None:
            arguments.append(node.args.vararg)
        annotations = [argument.annotation for argument in arguments if argument.annotation is not None]
    return annotations


def _boundary_message(roles: list[_IdRole], *, established: bool) -> str:
    names = ", ".join(f"`{role.name}`" for role in roles)
    if established:
        # Existing baselines fingerprint this message; expanded coverage must not invalidate them.
        return (
            f"{names} are swappable ID-shaped roles with the same carrier; introduce or reuse "
            "`typing.NewType` or nominal value-object identifiers and propagate them through this boundary."
        )
    return (
        f"{names} are swappable domain roles with the same carrier; introduce or reuse "
        "`typing.NewType` or nominal value-object types and propagate them through this boundary."
    )


def _canonical_source(source: NominalSource) -> bool:
    return (
        "NewType" in source.text
        and not _is_excluded_path(source.path)
        and {"tests", "test", "fixtures", "fakes"}.isdisjoint(source.path.parts)
        and not source.path.name.startswith("test_")
        and source.tree is not None
    )


def _canonical_roles(
    sources: dict[str, NominalSource], resolved: dict[tuple[str, str | None], _TypeFacts]
) -> dict[str, str]:
    candidates: dict[str, list[str]] = {}
    for module, source in sources.items():
        if not _canonical_source(source) or source.tree is None:
            continue
        facts = resolved.get((module, None), _TypeFacts({}, {}))
        for statement in source.tree.body:
            assignment = _alias_assignment(statement)
            if assignment is None or not _is_new_type_call(assignment.value, source.imports):
                continue
            name = assignment.target
            value = assignment.value
            if (
                len(value.args) != _MIN_SWAPPABLE_ROLES
                or value.keywords
                or not isinstance(value.args[0], ast.Constant)
                or value.args[0].value != name
            ):
                continue
            if name not in facts.nominal_aliases:
                continue
            first = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
            role = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", first).lower()
            candidates.setdefault(role, []).append(facts.nominal_aliases[name])
    return {name: shapes[0] for name, shapes in candidates.items() if len(shapes) == 1}
