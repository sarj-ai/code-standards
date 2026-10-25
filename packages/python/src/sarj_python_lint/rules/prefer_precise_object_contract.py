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
from sarj_python_lint.rules._test_composition import call_arguments, direct_nodes
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
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "Safe fixes narrow only a bare builtin object return annotation to builtin str for a closed private nested synchronous helper returning one exact string literal, with every call used directly as an if test and all containing return contracts explicit. Existing inert/metadata/binding proofs must hold; public/domain/container/parameter/model contracts and other result uses remain review-only.",
            "Checks builtin object in function signatures and class field annotations, including supported containers, callables, optional unions and quoted annotations. Local opaque values, object() sentinels, Literal/Annotated metadata, framework hooks, proven override signatures, and registered raw Pydantic callbacks are excluded. Functions that directly validate an object parameter through a source-visible model_validate call, positionally or with obj=, retain that raw boundary. JSON text inputs still require a text or byte contract. Aliases must resolve to their source declaration and their bodies use definition scope. Alias graphs are bounded and shared branches reuse their facts. Imported or shadowed application types named object are preserved. Genuine opaque public contracts can use an explained exact-code exception; narrowing outside the exact private truthiness-only subset remains manual.",
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
            RuleExample(
                example_id="safe-autofix-subset",
                title="Existing source proof permits a narrow convergent fix",
                outcome=ExampleOutcome.MATCH,
                scenario="private-literal-truthiness",
                files=(
                    ExampleFile.python(
                        "app/contracts.py",
                        "def ready() -> bool:\n    def _value() -> object:\n        return 'ready'\n    if _value():\n        return True\n    return False\n",
                    ),
                ),
                fixed_files=(
                    ExampleFile.python(
                        "app/contracts.py",
                        "def ready() -> bool:\n    def _value() -> str:\n        return 'ready'\n    if _value():\n        return True\n    return False\n",
                    ),
                ),
                focus_path=PurePosixPath("app/contracts.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="safe-autofix-result",
                title="The proven private literal return already has its precise type",
                outcome=ExampleOutcome.NO_MATCH,
                scenario="private-literal-truthiness",
                files=(
                    ExampleFile.python(
                        "app/contracts.py",
                        "def ready() -> bool:\n    def _value() -> str:\n        return 'ready'\n    if _value():\n        return True\n    return False\n",
                    ),
                ),
                focus_path=PurePosixPath("app/contracts.py"),
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
            if not _has_object(annotation, context, facts, at=annotation):
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


def _has_object(
    annotation: ast.expr,
    context: PythonFileContext,
    facts: MappingShapeFacts,
    *,
    at: ast.AST,
    depth: int = 0,
    aliases: dict[str, int] | None = None,
) -> bool:
    if depth >= _MAX_TYPE_DEPTH:
        return False
    node = context.annotation_semantics.parse(annotation)
    if node is None or (isinstance(node, ast.Name) and facts.shadowed(node.id, at)):
        return False
    if aliases is None:
        aliases = {}
    if isinstance(node, ast.Name) and node.id in context.annotation_semantics.aliases:
        value = facts.alias_value(node, at)
        if value is None or depth >= aliases.get(node.id, _MAX_TYPE_DEPTH):
            return False
        aliases[node.id] = depth
        return _has_object(value, context, facts, at=value, depth=depth + 1, aliases=aliases)
    members = _type_arguments(node, facts, at)
    if members is None:
        return _opaque(node, facts, at)
    return any(_has_object(member, context, facts, at=at, depth=depth + 1, aliases=aliases) for member in members)


def _type_arguments(node: ast.expr, facts: MappingShapeFacts, at: ast.AST) -> list[ast.expr] | None:
    match node:
        case ast.Subscript():
            wrapper = facts.qualified(node.value, at)
            if wrapper in {"typing.Literal", "typing_extensions.Literal"}:
                return []
            members = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            return members[:1] if wrapper in {"typing.Annotated", "typing_extensions.Annotated"} else members
        case ast.BinOp(op=ast.BitOr()):
            return [node.left, node.right]
        case ast.List() | ast.Tuple():
            return node.elts
        case _:
            return None


def _opaque(node: ast.expr, facts: MappingShapeFacts, at: ast.AST) -> bool:
    return facts.builtin(node, "object", at) or facts.qualified(node, at) == "builtins.object"


def _framework(function: ast.FunctionDef | ast.AsyncFunctionDef, context: PythonFileContext) -> bool:
    owner = context.parents.get(function)
    return isinstance(owner, ast.ClassDef) and (
        function.name in _FRAMEWORK_METHODS
        or (
            bool(owner.bases)
            and any(
                context.imports.resolves(node, sources=_TYPING, symbol="override") for node in function.decorator_list
            )
        )
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
        if node.func.attr != "model_validate":
            continue
        values = call_arguments(node, ("obj",))
        value = values.get("obj") if values is not None else None
        if not isinstance(value, ast.Name) or value.id not in parameters:
            continue
        model = contracts.class_type(node.func.value)
        if model is not None and contracts.inherits(model, MODEL_BASES | SETTINGS_BASES):
            return True
    return False
