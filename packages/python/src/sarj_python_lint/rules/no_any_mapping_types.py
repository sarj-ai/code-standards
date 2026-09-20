from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    is_suppressed,
)
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


_TYPING_SOURCES = frozenset({"typing", "typing_extensions"})
_PYDANTIC_SOURCES = frozenset({"pydantic"})
_MAPPING_SOURCES = frozenset({"collections.abc", "typing"})
_MAPPING_NAMES = frozenset({"dict", "Dict", "Mapping", "MutableMapping"})
_MAPPING_ARGUMENT_COUNT = 2


@final
class NoAnyMappingTypes(Rule):
    id = "no-any-mapping-types"
    code = "SARJ447"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="String-keyed mapping types must not erase their values with `Any`.",
        rationale=(
            "An `Any`-valued mapping disables checking transitively and conceals whether the value is a fixed record, "
            "an arbitrary JSON tree, or a genuinely opaque Python object."
        ),
        remediation=(
            "Use `TypedDict` (and `Unpack[TypedDict]` for closed keyword arguments) for fixed records, a Pydantic model "
            "for untrusted runtime input, `pydantic.JsonValue` for arbitrary JSON, or `object` plus explicit narrowing "
            "for a genuinely opaque Python value."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        aliases=("no-vague-annotations",),
        limitations=(
            (
                "Only proven built-in or standard-library string-keyed mappings whose value recursively contains "
                "`typing.Any` are reported; `object` is intentionally not treated as `Any`."
            ),
            "Generated and vendored sources are excluded; exact local suppressions remain auditable.",
        ),
        examples=(
            RuleExample(
                example_id="any-valued-mapping-annotation",
                title="An Any-valued mapping erases the record schema",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/offers.py", "from typing import Any\ndef details() -> dict[str, Any]: ...\n"
                    ),
                ),
                focus_path=PurePosixPath("app/offers.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="typed-dictionary-annotation",
                title="A TypedDict preserves the record schema",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/offers.py",
                        "from typing import TypedDict\nclass OfferDetails(TypedDict):\n    id: str\ndef details() -> OfferDetails: ...\n",
                    ),
                ),
                focus_path=PurePosixPath("app/offers.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source) or _is_vendor_path(path):
            return []
        try:
            tree = ast.parse(source, filename=str(path), type_comments=True)
        except SyntaxError:
            return []
        imports = ImportIndex.from_tree(tree, module_scope_only=True)
        aliases = _type_aliases(tree, imports)
        lines = source.splitlines()
        findings: list[Diagnostic] = []
        seen: set[tuple[int, int]] = set()
        for expression in _type_expressions(tree, imports):
            for mapping in _any_mappings(expression, imports, aliases):
                location = expression if isinstance(expression, ast.Constant) else mapping
                key = (location.lineno, location.col_offset)
                if key in seen or is_suppressed(lines, location.lineno, self.code):
                    continue
                seen.add(key)
                findings.append(
                    Diagnostic(
                        path=path,
                        line=location.lineno,
                        col=location.col_offset + 1,
                        code=self.code,
                        message=(
                            f"mapping type `{ast.unparse(mapping)}` contains `Any`; use `TypedDict` for a fixed "
                            "record, `pydantic.JsonValue` for arbitrary JSON, or `object` with narrowing for opaque values"
                        ),
                    )
                )
        return sorted(findings, key=lambda finding: (finding.line, finding.col))


def _type_expressions(tree: ast.Module, imports: ImportIndex) -> list[ast.expr]:
    expressions = [annotation for node in ast.walk(tree) if (annotation := _node_annotation(node, imports)) is not None]
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        if imports.resolves(node.func, sources=_TYPING_SOURCES, symbol="cast") or imports.resolves(
            node.func, sources=_PYDANTIC_SOURCES, symbol="TypeAdapter"
        ):
            expressions.append(node.args[0])
    return expressions


def _node_annotation(node: ast.AST, imports: ImportIndex) -> ast.expr | None:
    match node:
        case (
            ast.arg(annotation=annotation)
            | ast.FunctionDef(returns=annotation)
            | ast.AsyncFunctionDef(returns=annotation)
        ):
            return annotation
        case ast.AnnAssign(annotation=annotation, value=value) if value is not None:
            if imports.resolves(annotation, sources=_TYPING_SOURCES, symbol="TypeAlias"):
                return value
            return annotation
        case ast.AnnAssign(annotation=annotation):
            return annotation
        case ast.TypeAlias(value=value):
            return value
        case (
            ast.Assign(type_comment=str(comment))
            | ast.For(type_comment=str(comment))
            | ast.AsyncFor(type_comment=str(comment))
            | ast.With(type_comment=str(comment))
            | ast.AsyncWith(type_comment=str(comment))
        ):
            return _type_comment(comment, node)
        case _:
            return None


def _type_comment(comment: str, owner: ast.AST) -> ast.expr | None:
    try:
        expression = ast.parse(comment, mode="eval").body
    except SyntaxError:
        return None
    ast.copy_location(expression, owner)
    return expression


def _parse_string_annotation(annotation: ast.expr) -> ast.expr:
    if not isinstance(annotation, ast.Constant) or not isinstance(annotation.value, str):
        return annotation
    try:
        parsed = ast.parse(annotation.value, mode="eval").body
    except SyntaxError:
        return annotation
    ast.copy_location(parsed, annotation)
    return parsed


def _any_mappings(annotation: ast.expr, imports: ImportIndex, aliases: dict[str, ast.expr]) -> list[ast.Subscript]:
    resolved = _parse_string_annotation(annotation)
    return [
        node
        for node in ast.walk(resolved)
        if isinstance(node, ast.Subscript) and _is_any_mapping(node, imports, aliases)
    ]


def _is_any_mapping(node: ast.Subscript, imports: ImportIndex, aliases: dict[str, ast.expr]) -> bool:
    if not isinstance(node.slice, ast.Tuple) or len(node.slice.elts) != _MAPPING_ARGUMENT_COUNT:
        return False
    target = node.value
    mapping = (isinstance(target, ast.Name) and target.id == "dict" and imports.builtin_is_unshadowed("dict")) or any(
        imports.resolves(target, sources=_MAPPING_SOURCES, symbol=name) for name in _MAPPING_NAMES
    )
    if not mapping:
        return False
    key, value = node.slice.elts
    return _is_builtin_str(key, imports) and _contains_any(value, imports, aliases, seen=frozenset())


def _is_builtin_str(node: ast.expr, imports: ImportIndex) -> bool:
    return isinstance(node, ast.Name) and node.id == "str" and imports.builtin_is_unshadowed("str")


def _contains_any(
    node: ast.expr,
    imports: ImportIndex,
    aliases: dict[str, ast.expr],
    *,
    seen: frozenset[str],
) -> bool:
    node = _parse_string_annotation(node)
    if imports.resolves(node, sources=_TYPING_SOURCES, symbol="Any"):
        return True
    if isinstance(node, ast.Name) and node.id in aliases and node.id not in seen:
        return _contains_any(aliases[node.id], imports, aliases, seen=seen | {node.id})
    return any(
        _contains_any(child, imports, aliases, seen=seen)
        for child in ast.iter_child_nodes(node)
        if isinstance(child, ast.expr)
    )


def _type_aliases(tree: ast.Module, imports: ImportIndex) -> dict[str, ast.expr]:
    aliases: dict[str, ast.expr] = {}
    ambiguous: set[str] = set()
    for statement in tree.body:
        name: str | None = None
        value: ast.expr | None = None
        match statement:
            case ast.TypeAlias(name=ast.Name(id=alias), value=alias_value, type_params=[]):
                name, value = alias, alias_value
            case ast.AnnAssign(target=ast.Name(id=alias), annotation=annotation, value=alias_value) if (
                alias_value is not None and imports.resolves(annotation, sources=_TYPING_SOURCES, symbol="TypeAlias")
            ):
                name, value = alias, alias_value
            case _:
                pass
        if name is None or value is None:
            continue
        if name in aliases:
            ambiguous.add(name)
        else:
            aliases[name] = value
    for name in ambiguous:
        aliases.pop(name, None)
    return aliases


def _is_vendor_path(path: Path) -> bool:
    return any(part.casefold() in {"vendor", "vendored", "third_party"} for part in path.parts)
