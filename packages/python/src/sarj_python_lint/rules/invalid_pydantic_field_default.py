from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, NamedTuple, final, override

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


if TYPE_CHECKING:
    from pathlib import Path


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


@dataclass(frozen=True, slots=True)
class _LiteralDomain:
    values: frozenset[_LiteralKey]


class _LiteralKey(NamedTuple):
    value_type: type[object]
    value: object


class _BoundViolation(NamedTuple):
    bound_name: str
    bound: object


@final
class InvalidPydanticFieldDefault(Rule):
    id = "invalid-pydantic-field-default"
    code = "SARJ400"
    documentation = RuleDocumentation(
        summary="Require literal Pydantic `Field` defaults to satisfy their declared contract.",
        rationale=(
            "An invalid default lets a model begin with a value that contradicts its annotation or field bounds, "
            "moving a deterministic configuration error into runtime validation."
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
                "numeric or string-length bounds."
            ),
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
                        "from pydantic import BaseModel, Field\n\n"
                        "class RetryPolicy(BaseModel):\n"
                        "    attempts: int = Field(default=0, gt=0)\n",
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
                        "from pydantic import BaseModel, Field\n\n"
                        "class RetryPolicy(BaseModel):\n"
                        "    attempts: int = Field(default=1, gt=0)\n",
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
                if statement.target.id.startswith("_") or not isinstance(statement.value, ast.Call):
                    continue
                call = statement.value
                if not imports.resolves(call.func, sources=_PYDANTIC_FIELD_SOURCES, symbol="Field"):
                    continue
                default = _field_default(call)
                if default is None:
                    continue
                message = _invalid_default_message(statement.target.id, statement.annotation, default, call, imports)
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


def _field_default(call: ast.Call) -> ast.expr | None:
    positional = call.args[0] if call.args else None
    keywords = [keyword.value for keyword in call.keywords if keyword.arg == "default"]
    if (positional is not None and keywords) or (len(keywords) != 1 and positional is None):
        return None
    default = positional if positional is not None else keywords[0]
    if isinstance(default, ast.Constant) and default.value is Ellipsis:
        return None
    return default


def _invalid_default_message(
    field_name: str,
    annotation: ast.expr,
    default: ast.expr,
    call: ast.Call,
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

    violation = _bound_violation(literal, call)
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


def _bound_violation(default: object, call: ast.Call) -> _BoundViolation | None:
    bounds = {keyword.arg: _literal_value(keyword.value) for keyword in call.keywords if keyword.arg is not None}
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
