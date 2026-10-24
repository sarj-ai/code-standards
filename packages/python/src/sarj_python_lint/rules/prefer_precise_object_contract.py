from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

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
)
from sarj_python_lint.rules._declared_contracts import MODEL_BASES, SETTINGS_BASES, DeclaredContracts
from sarj_python_lint.rules._test_composition import direct_nodes
from sarj_python_lint.rules.require_pydantic_for_mapping_shape import MappingShapeFacts


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext


_TYPING = frozenset({"typing", "typing_extensions"})
_MAX_TYPE_DEPTH = 32
_FRAMEWORK_METHODS = frozenset(
    {"__eq__", "__ne__", "__hash__", "__get_pydantic_core_schema__", "__get_pydantic_json_schema__", "model_post_init"}
)


@final
class PreferPreciseObjectContract(Rule):
    id = "prefer-precise-object-contract"
    code = "SARJ528"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Use a precise type for declared application contracts instead of object.",
        rationale="An object annotation hides the operations and data the caller actually supplies. It often spreads casts and handwritten shape checks into consumers.",
        remediation="Use a concrete domain type, Protocol, TypeVar, Pydantic model or JsonValue as appropriate. Importer callables return types.ModuleType. Keep object for genuinely opaque Python values and raw validation boundaries with an explained local exception when necessary; never replace it with Any or a cast.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks builtin object in function signatures and class field annotations, including supported containers, callables, optional unions and quoted annotations. Local opaque values, object() sentinels, Literal/Annotated metadata, framework hooks, proven override signatures, and registered raw Pydantic callbacks are excluded. Functions that directly validate an object parameter through a source-visible model_validate call retain that raw boundary. Imported or shadowed application types named object are preserved. Genuine opaque public contracts can use an explained exact-code exception; no automatic narrowing.",
        ),
        examples=(
            RuleExample(
                example_id="opaque-importer",
                title="The importer erases its module result",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app.py",
                        "from collections.abc import Callable\ndef load(import_module: Callable[[str], object]): ...\n",
                    ),
                ),
                focus_path=PurePosixPath("app.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="module-contract",
                title="A module result has its standard type",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app.py",
                        "from collections.abc import Callable\nfrom types import ModuleType\ndef load(import_module: Callable[[str], ModuleType]): ...\n",
                    ),
                ),
                focus_path=PurePosixPath("app.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.tree is None or context.generated or "object" not in context.symbol_source:
            return []
        facts = MappingShapeFacts(context)
        if facts.provenance.wildcard:
            return []
        findings: list[Diagnostic] = []
        contracts = DeclaredContracts(context)
        for owner, annotation in _contracts(context):
            if not any(
                _opaque(member, context, facts, annotation)
                for member in _type_members(annotation, context, facts, at=annotation)
            ):
                continue
            function = owner if isinstance(owner, ast.FunctionDef | ast.AsyncFunctionDef) else None
            if function is not None and (
                _framework(function, context)
                or facts.raw_boundary(annotation)
                or _validated_input(function, annotation, contracts)
            ):
                continue
            findings.append(
                Diagnostic(
                    context.path,
                    annotation.lineno,
                    annotation.col_offset + 1,
                    self.code,
                    "Replace object with the actual domain type, a narrow Protocol, a TypeVar or a validated Pydantic contract; importer callables return ModuleType. Keep genuinely opaque boundaries explicit.",
                    severity=Severity.WARNING,
                )
            )
        return findings


def _contracts(context: PythonFileContext) -> Iterator[tuple[ast.AST, ast.expr]]:
    for function in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef):
        for argument in (
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
            *((function.args.vararg,) if function.args.vararg else ()),
            *((function.args.kwarg,) if function.args.kwarg else ()),
        ):
            if argument.annotation is not None:
                yield function, argument.annotation
        if function.returns is not None:
            yield function, function.returns
    for field in context.nodes(ast.AnnAssign):
        if isinstance(context.parents.get(field), ast.ClassDef):
            yield field, field.annotation


def _type_members(
    annotation: ast.expr,
    context: PythonFileContext,
    facts: MappingShapeFacts,
    *,
    at: ast.AST,
    depth: int = 0,
    aliases: frozenset[str] = frozenset(),
) -> Iterator[ast.expr]:
    if depth >= _MAX_TYPE_DEPTH:
        return
    node = context.annotation_semantics.parse(annotation)
    if node is None:
        return
    if isinstance(node, ast.Name) and facts.shadowed(node.id, at):
        return
    if isinstance(node, ast.Name) and node.id in context.annotation_semantics.aliases:
        if node.id not in aliases:
            yield from _type_members(
                context.annotation_semantics.aliases[node.id],
                context,
                facts,
                at=at,
                depth=depth + 1,
                aliases=aliases | {node.id},
            )
        return
    members = _type_arguments(node, context)
    if members is None:
        yield node
        return
    for member in members:
        yield from _type_members(member, context, facts, at=at, depth=depth + 1, aliases=aliases)


def _type_arguments(node: ast.expr, context: PythonFileContext) -> list[ast.expr] | None:
    match node:
        case ast.Subscript():
            if context.imports.resolves(node.value, sources=_TYPING, symbol="Literal"):
                return []
            members = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            return members[:1] if context.imports.resolves(node.value, sources=_TYPING, symbol="Annotated") else members
        case ast.BinOp(op=ast.BitOr()):
            return [node.left, node.right]
        case ast.List() | ast.Tuple():
            return node.elts
        case _:
            return None


def _opaque(node: ast.expr, context: PythonFileContext, facts: MappingShapeFacts, at: ast.AST) -> bool:
    return (facts.builtin(node, "object", at) and context.imports.builtin_is_unshadowed("object")) or facts.qualified(
        node, at
    ) == "builtins.object"


def _framework(function: ast.FunctionDef | ast.AsyncFunctionDef, context: PythonFileContext) -> bool:
    return function.name in _FRAMEWORK_METHODS or any(
        context.imports.resolves(node, sources=_TYPING, symbol="override") for node in function.decorator_list
    )


def _validated_input(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    annotation: ast.expr,
    contracts: DeclaredContracts,
) -> bool:
    parameters = {
        arg.arg
        for arg in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
        if arg.annotation is annotation
    }
    if not parameters:
        return False
    for node in direct_nodes(function):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"model_validate", "model_validate_json"} or not node.args:
            continue
        if not isinstance(node.args[0], ast.Name) or node.args[0].id not in parameters:
            continue
        model = contracts.class_type(node.func.value)
        if model is not None and contracts.inherits(model, MODEL_BASES | SETTINGS_BASES):
            return True
    return False
