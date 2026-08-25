from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import NamedTuple, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    parse_or_none,
)
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path


_PYDANTIC_BASE_MODEL_SOURCES = frozenset({"pydantic", "pydantic.main"})
_PYDANTIC_FIELD_SOURCES = frozenset({"pydantic", "pydantic.fields"})
_TYPING_SOURCES = frozenset({"typing", "typing_extensions"})
_COLLECTION_SOURCES = frozenset({"collections.abc", "typing", "typing_extensions"})
_KNOWN_NON_NULL_BUILTINS = frozenset(
    {
        "bool",
        "bytearray",
        "bytes",
        "complex",
        "dict",
        "float",
        "frozenset",
        "int",
        "list",
        "memoryview",
        "range",
        "set",
        "str",
        "tuple",
        "type",
    }
)
_KNOWN_NON_NULL_TYPING = frozenset(
    {
        "BinaryIO",
        "Callable",
        "Collection",
        "Container",
        "Dict",
        "FrozenSet",
        "IO",
        "Iterable",
        "Iterator",
        "List",
        "Mapping",
        "Match",
        "MutableMapping",
        "MutableSequence",
        "MutableSet",
        "Pattern",
        "Reversible",
        "Sequence",
        "Set",
        "Sized",
        "TextIO",
        "Tuple",
        "Type",
    }
)
_MISSING = object()
_MAX_ALIAS_HOPS = 4
_MAX_PATH_ANCESTORS = 12
_MAX_IMPORTED_MODULE_BYTES = 256_000


@dataclass(frozen=True, slots=True)
class _LiteralDomain:
    values: frozenset[_LiteralKey]


class _LiteralKey(NamedTuple):
    value_type: type[object]
    value: object


class _BoundViolation(NamedTuple):
    bound_name: str
    bound: object


class _AnnotationContract(NamedTuple):
    annotation: ast.expr
    imports: ImportIndex
    constraints: tuple[ast.Call, ...]


class _ImportedSymbol(NamedTuple):
    module: str
    level: int
    symbol: str


@final
class InvalidPydanticFieldDefault(Rule):
    id = "invalid-pydantic-field-default"
    code = "SARJ400"
    documentation = RuleDocumentation(
        summary="Require literal Pydantic `Field` defaults to satisfy their declared contract.",
        rationale=(
            "Pydantic does not validate defaults by default, so an invalid literal can enter a model while "
            "contradicting its annotation or field bounds."
        ),
        remediation=(
            "Choose a default allowed by the annotation and every literal `Field` bound, or widen the contract "
            "when the value is intentional."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "The rule checks direct public fields on classes that directly inherit Pydantic `BaseModel`.",
            (
                "It reports only statically provable literal conflicts with nullability, `Literal` domains, and "
                "numeric or string-length bounds from assignment or `Annotated` Field metadata."
            ),
            "Imported annotation aliases are followed only to a unique local Python module within the same checkout.",
            "Test and generated files are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="default-violates-lower-bound",
                title="Default is outside the declared field bounds",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from typing import Annotated\nfrom pydantic import BaseModel, Field\n\n"
                        "PositiveInt = Annotated[int, Field(gt=0)]\n\n"
                        "class RetryPolicy(BaseModel):\n"
                        "    attempts: PositiveInt = 0\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="default-satisfies-lower-bound",
                title="Default satisfies the declared field bounds",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from typing import Annotated\nfrom pydantic import BaseModel, Field\n\n"
                        "PositiveInt = Annotated[int, Field(gt=0)]\n\n"
                        "class RetryPolicy(BaseModel):\n"
                        "    attempts: PositiveInt = 1\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_test_path(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        imports = ImportIndex.from_tree(tree)
        diagnostics: list[Diagnostic] = []
        for class_node in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
            if not _is_direct_base_model(class_node, imports):
                continue
            for statement in class_node.body:
                if not isinstance(statement, ast.AnnAssign) or not isinstance(statement.target, ast.Name):
                    continue
                if statement.target.id.startswith("_"):
                    continue
                contract = _annotation_contract(path, tree, statement.annotation)
                assignment_field = (
                    statement.value
                    if isinstance(statement.value, ast.Call)
                    and imports.resolves(statement.value.func, sources=_PYDANTIC_FIELD_SOURCES, symbol="Field")
                    else None
                )
                constraints = (*contract.constraints, *((assignment_field,) if assignment_field is not None else ()))
                default = _declared_default(statement.value, assignment_field, contract.constraints)
                if default is None:
                    continue
                message = _invalid_default_message(
                    statement.target.id,
                    contract.annotation,
                    default,
                    constraints,
                    contract.imports,
                )
                if message is None:
                    continue
                diagnostics.append(
                    Diagnostic(
                        path=path,
                        line=default.lineno,
                        col=default.col_offset + 1,
                        code=self.code,
                        message=message,
                    )
                )
        return diagnostics


def _is_direct_base_model(node: ast.ClassDef, imports: ImportIndex) -> bool:
    return len(node.bases) == 1 and imports.resolves(
        node.bases[0], sources=_PYDANTIC_BASE_MODEL_SOURCES, symbol="BaseModel"
    )


def _declared_default(
    assigned: ast.expr | None,
    assignment_field: ast.Call | None,
    annotation_fields: tuple[ast.Call, ...],
) -> ast.expr | None:
    if assignment_field is not None:
        return _field_default(assignment_field)
    if assigned is not None:
        return assigned
    embedded = tuple(default for call in annotation_fields if (default := _field_default(call)) is not None)
    return embedded[0] if len(embedded) == 1 else None


def _field_default(call: ast.Call) -> ast.expr | None:
    positional = call.args[0] if call.args else None
    keywords = [keyword.value for keyword in call.keywords if keyword.arg == "default"]
    if (positional is not None and keywords) or (len(keywords) != 1 and positional is None):
        return None
    default = positional if positional is not None else keywords[0]
    if isinstance(default, ast.Constant) and default.value is Ellipsis:
        return None
    return default


def _annotation_contract(path: Path, tree: ast.Module, annotation: ast.expr) -> _AnnotationContract:
    return _resolve_annotation_contract(path, tree, annotation, seen=frozenset(), depth=0)


def _resolve_annotation_contract(
    path: Path,
    tree: ast.Module,
    annotation: ast.expr,
    *,
    seen: frozenset[tuple[Path, str]],
    depth: int,
) -> _AnnotationContract:
    imports = ImportIndex.from_tree(tree)
    annotation = _parse_forward_annotation(annotation)
    if depth >= _MAX_ALIAS_HOPS:
        return _AnnotationContract(annotation, imports, ())
    if isinstance(annotation, ast.Name):
        local = _module_alias_expression(tree, annotation.id)
        if local is not None:
            return _resolve_annotation_contract(path, tree, local, seen=seen, depth=depth + 1)
        imported = _imported_symbol(tree, annotation.id)
        target = _resolve_imported_module(path, imported) if imported is not None else None
        if target is not None and imported is not None and (target, imported.symbol) not in seen:
            key = (target, imported.symbol)
            target_tree = _read_module(target)
            target_value = _module_alias_expression(target_tree, imported.symbol) if target_tree is not None else None
            if target_tree is not None and target_value is not None:
                return _resolve_annotation_contract(
                    target,
                    target_tree,
                    target_value,
                    seen=seen | {key},
                    depth=depth + 1,
                )
    if isinstance(annotation, ast.Subscript) and imports.resolves(
        annotation.value, sources=_TYPING_SOURCES, symbol="Annotated"
    ):
        members = _slice_members(annotation.slice)
        if members:
            base = _resolve_annotation_contract(path, tree, members[0], seen=seen, depth=depth + 1)
            fields = tuple(
                member
                for member in members[1:]
                if isinstance(member, ast.Call)
                and imports.resolves(member.func, sources=_PYDANTIC_FIELD_SOURCES, symbol="Field")
            )
            return _AnnotationContract(base.annotation, base.imports, (*base.constraints, *fields))
    return _AnnotationContract(annotation, imports, ())


def _module_alias_expression(tree: ast.Module, symbol: str) -> ast.expr | None:
    candidates = [value for statement in tree.body if (value := _alias_value(statement, symbol)) is not None]
    return candidates[0] if len(candidates) == 1 else None


def _alias_value(statement: ast.stmt, symbol: str) -> ast.expr | None:
    match statement:
        case ast.TypeAlias(name=ast.Name(id=name), value=value) if name == symbol:
            return value
        case ast.AnnAssign(target=ast.Name(id=name), value=value) if name == symbol:
            return value
        case ast.Assign(targets=[ast.Name(id=name)], value=value) if name == symbol:
            return value
        case _:
            return None


def _imported_symbol(tree: ast.Module, local_name: str) -> _ImportedSymbol | None:
    candidates = [
        _ImportedSymbol(statement.module or "", statement.level, alias.name)
        for statement in tree.body
        if isinstance(statement, ast.ImportFrom)
        for alias in statement.names
        if alias.name != "*" and (alias.asname or alias.name) == local_name
    ]
    return candidates[0] if len(candidates) == 1 else None


def _resolve_imported_module(current: Path, reference: _ImportedSymbol) -> Path | None:
    if not current.is_absolute():
        return None
    current = current.resolve()
    checkout = _checkout_root(current)
    if checkout is None:
        return None
    module_parts = tuple(part for part in reference.module.split(".") if part)
    candidates: set[Path] = set()
    if reference.level:
        base = current.parent
        for _ in range(reference.level - 1):
            base = base.parent
        candidates.update(_module_files(base.joinpath(*module_parts), checkout))
    elif module_parts:
        for depth, ancestor in enumerate((current.parent, *current.parents)):
            if depth >= _MAX_PATH_ANCESTORS:
                break
            candidates.update(_module_files(ancestor.joinpath(*module_parts), checkout))
    return next(iter(candidates)) if len(candidates) == 1 else None


def _checkout_root(path: Path) -> Path | None:
    for depth, ancestor in enumerate(path.parents):
        if depth >= _MAX_PATH_ANCESTORS:
            break
        if (ancestor / ".git").exists():
            return ancestor.resolve()
    return None


def _module_files(base: Path, checkout: Path) -> frozenset[Path]:
    resolved: set[Path] = set()
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if not candidate.is_file() or candidate.is_symlink():
            continue
        target = candidate.resolve()
        if target.is_relative_to(checkout):
            resolved.add(target)
    return frozenset(resolved)


def _read_module(path: Path) -> ast.Module | None:
    try:
        if path.stat().st_size > _MAX_IMPORTED_MODULE_BYTES:
            return None
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    except OSError, SyntaxError:
        return None
    return tree


def _invalid_default_message(
    field_name: str,
    annotation: ast.expr,
    default: ast.expr,
    constraints: tuple[ast.Call, ...],
    imports: ImportIndex,
) -> str | None:
    literal = _literal_value(default)
    if literal is _MISSING:
        return None
    if literal is None and _provably_non_null(annotation, imports):
        return (
            f"`{field_name}` gives `Field` a `None` default, but its direct annotation excludes `None`; "
            "include `None` in the annotation or provide a non-null default."
        )

    domain = _literal_domain(annotation, imports)
    if domain is not None and not isinstance(literal, float) and _literal_key(literal) not in domain.values:
        allowed = ", ".join(sorted(repr(item.value) for item in domain.values))
        return (
            f"`{field_name}` defaults to {literal!r}, outside its direct `Literal` domain ({allowed}); "
            "use one of the declared literal values."
        )

    violation = _bound_violation(literal, constraints)
    if violation is not None:
        bound_name = violation.bound_name
        bound = violation.bound
        return (
            f"`{field_name}` defaults to {literal!r}, which violates `Field({bound_name}={bound!r})`; "
            "choose a default inside the declared bounds."
        )
    return None


def _literal_value(node: ast.expr) -> object:
    match node:
        case ast.Constant(value=(str() | bytes() | bool() | int() | float() | None) as value):
            return value
        case ast.UnaryOp(op=(ast.USub() | ast.UAdd()) as operator, operand=ast.Constant(value=value)) if isinstance(
            value, (int, float)
        ) and not isinstance(value, bool):
            return -value if isinstance(operator, ast.USub) else value
        case _:
            return _MISSING


def _literal_key(value: object) -> _LiteralKey:
    return _LiteralKey(type(value), value)


def _literal_domain(node: ast.expr, imports: ImportIndex) -> _LiteralDomain | None:
    node = _parse_forward_annotation(node)
    if isinstance(node, ast.Constant) and node.value is None:
        return _LiteralDomain(frozenset({_literal_key(None)}))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _merge_domains((_literal_domain(node.left, imports), _literal_domain(node.right, imports)))
    if not isinstance(node, ast.Subscript):
        return None
    if imports.resolves(node.value, sources=_TYPING_SOURCES, symbol="Annotated"):
        members = _slice_members(node.slice)
        return _literal_domain(members[0], imports) if members else None
    if imports.resolves(node.value, sources=_TYPING_SOURCES, symbol="Optional"):
        domain = _literal_domain(node.slice, imports)
        if domain is None:
            return None
        return _LiteralDomain(domain.values | {_literal_key(None)})
    if imports.resolves(node.value, sources=_TYPING_SOURCES, symbol="Union"):
        return _merge_domains(tuple(_literal_domain(member, imports) for member in _slice_members(node.slice)))
    if not imports.resolves(node.value, sources=_TYPING_SOURCES, symbol="Literal"):
        return None
    values: set[_LiteralKey] = set()
    for member in _slice_members(node.slice):
        value = _literal_value(member)
        if value is _MISSING or isinstance(value, float):
            return None
        values.add(_literal_key(value))
    return _LiteralDomain(frozenset(values)) if values else None


def _merge_domains(domains: tuple[_LiteralDomain | None, ...]) -> _LiteralDomain | None:
    if not domains or any(domain is None for domain in domains):
        return None
    values: set[_LiteralKey] = set()
    for domain in domains:
        if domain is not None:
            values.update(domain.values)
    return _LiteralDomain(frozenset(values))


def _provably_non_null(node: ast.expr, imports: ImportIndex) -> bool:
    node = _parse_forward_annotation(node)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _provably_non_null(node.left, imports) and _provably_non_null(node.right, imports)
    if isinstance(node, ast.Name):
        return node.id in _KNOWN_NON_NULL_BUILTINS and imports.builtin_is_unshadowed(node.id)
    if not isinstance(node, ast.Subscript):
        return False
    if isinstance(node.value, ast.Name) and node.value.id in _KNOWN_NON_NULL_BUILTINS:
        return imports.builtin_is_unshadowed(node.value.id)
    if imports.resolves(node.value, sources=_TYPING_SOURCES, symbol="Annotated"):
        members = _slice_members(node.slice)
        return bool(members) and _provably_non_null(members[0], imports)
    if imports.resolves(node.value, sources=_TYPING_SOURCES, symbol="Literal"):
        domain = _literal_domain(node, imports)
        return domain is not None and _literal_key(None) not in domain.values
    if imports.resolves(node.value, sources=_TYPING_SOURCES, symbol="Optional"):
        return False
    if imports.resolves(node.value, sources=_TYPING_SOURCES, symbol="Union"):
        members = _slice_members(node.slice)
        return bool(members) and all(_provably_non_null(member, imports) for member in members)
    return any(
        imports.resolves(node.value, sources=_COLLECTION_SOURCES, symbol=symbol) for symbol in _KNOWN_NON_NULL_TYPING
    )


def _bound_violation(default: object, constraints: tuple[ast.Call, ...]) -> _BoundViolation | None:
    bounds = {
        keyword.arg: _literal_value(keyword.value)
        for call in constraints
        for keyword in call.keywords
        if keyword.arg is not None
    }
    if isinstance(default, (int, float)) and not isinstance(default, bool):
        for name in ("gt", "ge", "lt", "le"):
            bound = bounds.get(name, _MISSING)
            if not isinstance(bound, (int, float)) or isinstance(bound, bool):
                continue
            if _numeric_bound_is_violated(name, default, bound):
                return _BoundViolation(name, bound)
        return None
    if isinstance(default, (str, bytes)):
        for name in ("min_length", "max_length"):
            bound = bounds.get(name, _MISSING)
            if not isinstance(bound, int) or isinstance(bound, bool) or bound < 0:
                continue
            if (name == "min_length" and len(default) < bound) or (name == "max_length" and len(default) > bound):
                return _BoundViolation(name, bound)
    return None


def _numeric_bound_is_violated(name: str, default: float, bound: float) -> bool:
    match name:
        case "gt":
            return default <= bound
        case "ge":
            return default < bound
        case "lt":
            return default >= bound
        case "le":
            return default > bound
        case _:
            return False


def _parse_forward_annotation(node: ast.expr) -> ast.expr:
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        return node
    try:
        return ast.parse(node.value, mode="eval").body
    except SyntaxError:
        return node


def _slice_members(node: ast.expr) -> tuple[ast.expr, ...]:
    return tuple(node.elts) if isinstance(node, ast.Tuple) else (node,)
