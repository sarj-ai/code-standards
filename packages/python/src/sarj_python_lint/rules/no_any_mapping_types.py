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
    Severity,
    is_suppressed,
)
from sarj_python_lint.rules._annotation_semantics import AnnotationSemantics, scope_bound_names
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_python_lint.rules._imports import ImportIndex


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
        default_level=Severity.WARNING,
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
            (
                "Unique unconditional module-level PEP 695 and explicit TypeAlias chains are resolved with cycle "
                "guards. Plain module assignments are checked only when they directly define an Any-valued mapping "
                "used in a module-level annotation; imported, conditional, rebound, and ambiguous aliases are excluded."
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
        semantics = AnnotationSemantics.from_tree(tree)
        imports = semantics.imports
        parents = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        scope_cache: dict[int, frozenset[str]] = {}
        lines = source.splitlines()
        findings: list[Diagnostic] = []
        seen: set[tuple[int, int]] = set()
        expressions = [*_type_expressions(tree, imports, parents, scope_cache), *_implicit_mapping_aliases(tree)]
        for expression, owner in expressions:
            for mapping, location in _unshadowed_any_mappings(expression, owner, semantics, parents, scope_cache):
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


def _implicit_mapping_aliases(tree: ast.Module) -> list[tuple[ast.expr, ast.Assign]]:
    bindings = [scope_bound_names([statement]) for statement in tree.body]
    aliases: list[tuple[ast.expr, ast.Assign]] = []
    for statement in tree.body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target = statement.targets[0]
        if not isinstance(target, ast.Name) or not isinstance(statement.value, ast.Subscript):
            continue
        if sum(target.id in names for names in bindings) != 1:
            continue
        if _used_in_module_annotation(tree, target.id):
            aliases.append((statement.value, statement))
    return aliases


def _used_in_module_annotation(tree: ast.Module, name: str) -> bool:
    return any(
        _annotation_contains_name(annotation, name)
        for statement in tree.body
        for annotation in _module_statement_annotations(statement, name)
    )


def _module_statement_annotations(statement: ast.stmt, alias_name: str) -> list[ast.expr]:
    if isinstance(statement, ast.AnnAssign):
        return [statement.annotation]
    if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return []
    arguments = statement.args
    parameters = (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
    if any(argument.arg == alias_name for argument in parameters):
        return []
    annotations = [argument.annotation for argument in parameters if argument.annotation is not None]
    if statement.returns is not None:
        annotations.append(statement.returns)
    return annotations


def _annotation_contains_name(annotation: ast.expr, name: str) -> bool:
    parsed = annotation
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            parsed = ast.parse(annotation.value, mode="eval").body
        except SyntaxError:
            return False
    return any(isinstance(node, ast.Name) and node.id == name for node in ast.walk(parsed))


def _unshadowed_any_mappings(
    expression: ast.expr,
    owner: ast.AST,
    semantics: AnnotationSemantics,
    parents: dict[int, ast.AST],
    scope_cache: dict[int, frozenset[str]],
) -> list[tuple[ast.Subscript, ast.expr]]:
    parsed = semantics.parse(expression)
    if parsed is None:
        return []
    names = {node.id for node in ast.walk(parsed) if isinstance(node, ast.Name)}
    if not names.isdisjoint(_shadowed_names(owner, parents, scope_cache)):
        return []
    return [
        (mapping, expression if isinstance(expression, ast.Constant) else mapping)
        for mapping in _any_mappings(expression, semantics)
    ]


def _type_expressions(
    tree: ast.Module,
    imports: ImportIndex,
    parents: dict[int, ast.AST],
    scope_cache: dict[int, frozenset[str]],
) -> list[tuple[ast.expr, ast.AST]]:
    expressions = [
        (annotation, node) for node in ast.walk(tree) if (annotation := _node_annotation(node, imports)) is not None
    ]
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        function_names = {child.id for child in ast.walk(node.func) if isinstance(child, ast.Name)}
        if not function_names.isdisjoint(_shadowed_names(node, parents, scope_cache)):
            continue
        if imports.resolves(node.func, sources=_TYPING_SOURCES, symbol="cast") or imports.resolves(
            node.func, sources=_PYDANTIC_SOURCES, symbol="TypeAdapter"
        ):
            expressions.append((node.args[0], node))
    return expressions


def _shadowed_names(
    node: ast.AST,
    parents: dict[int, ast.AST],
    scope_cache: dict[int, frozenset[str]],
) -> set[str]:
    shadowed: set[str] = set()
    crossed_function_body = False
    below = node
    parent = parents.get(id(below))
    while parent is not None:
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if below in parent.body:
                crossed_function_body = True
                shadowed.update(_scope_names(parent, scope_cache))
        elif isinstance(parent, ast.ClassDef) and below in parent.body and not crossed_function_body:
            shadowed.update(_scope_names(parent, scope_cache))
        below = parent
        parent = parents.get(id(below))
    return shadowed


def _scope_names(
    owner: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    cache: dict[int, frozenset[str]],
) -> frozenset[str]:
    key = id(owner)
    if (cached := cache.get(key)) is not None:
        return cached
    names = scope_bound_names(owner.body)
    if isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
        names.update(
            argument.arg
            for argument in (
                *owner.args.posonlyargs,
                *owner.args.args,
                *owner.args.kwonlyargs,
                *((owner.args.vararg,) if owner.args.vararg is not None else ()),
                *((owner.args.kwarg,) if owner.args.kwarg is not None else ()),
            )
        )
    result = frozenset(names)
    cache[key] = result
    return result


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


def _any_mappings(annotation: ast.expr, semantics: AnnotationSemantics) -> list[ast.Subscript]:
    resolved = semantics.parse(annotation)
    if resolved is None:
        return []
    return [node for node in ast.walk(resolved) if isinstance(node, ast.Subscript) and _is_any_mapping(node, semantics)]


def _is_any_mapping(node: ast.Subscript, semantics: AnnotationSemantics) -> bool:
    if not isinstance(node.slice, ast.Tuple) or len(node.slice.elts) != _MAPPING_ARGUMENT_COUNT:
        return False
    imports = semantics.imports
    target = node.value
    mapping = (isinstance(target, ast.Name) and target.id == "dict" and imports.builtin_is_unshadowed("dict")) or any(
        imports.resolves(target, sources=_MAPPING_SOURCES, symbol=name) for name in _MAPPING_NAMES
    )
    if not mapping:
        return False
    key, value = node.slice.elts
    return _is_builtin_str(key, imports) and _contains_any(value, semantics, seen=frozenset())


def _is_builtin_str(node: ast.expr, imports: ImportIndex) -> bool:
    return isinstance(node, ast.Name) and node.id == "str" and imports.builtin_is_unshadowed("str")


def _contains_any(
    node: ast.expr,
    semantics: AnnotationSemantics,
    *,
    seen: frozenset[str],
) -> bool:
    parsed = semantics.parse(node)
    if parsed is None:
        return False
    imports = semantics.imports
    if imports.resolves(parsed, sources=_TYPING_SOURCES, symbol="Any"):
        return True
    if isinstance(parsed, ast.Name) and parsed.id in semantics.aliases and parsed.id not in seen:
        return _contains_any(semantics.aliases[parsed.id], semantics, seen=seen | {parsed.id})
    return any(
        _contains_any(child, semantics, seen=seen)
        for child in ast.iter_child_nodes(parsed)
        if isinstance(child, ast.expr)
    )


def _is_vendor_path(path: Path) -> bool:
    return any(part.casefold() in {"vendor", "vendored", "third_party"} for part in path.parts)
