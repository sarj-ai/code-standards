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
from sarj_python_lint.rules._imports import TYPING_SOURCES


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._imports import ImportIndex


_CONTAINERS = frozenset({"dict", "list", "set"})
_MAPPING_SLOTS = 2
_SLOTS = frozenset({"object", "str", "int", "bool", "float", "bytes"})
_BUILTINS = _SLOTS | _CONTAINERS | {"isinstance"}
_MUTATION_TARGETS = {f"builtins.{symbol}" for symbol in _BUILTINS} | {
    "typing.TypeGuard",
    "typing.TypeIs",
    "typing_extensions.TypeGuard",
    "typing_extensions.TypeIs",
}
_BAD = "from typing import TypeGuard\ndef is_mapping(value: object) -> TypeGuard[dict[str, object]]:\n    return isinstance(value, dict)\n"
_GOOD = _BAD.replace("dict[str, object]", "dict[object, object]")


@final
class NoShallowContainerTypeGuard(Rule):
    id = "no-shallow-container-type-guard"
    code = "SARJ472"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Do not claim typed container contents from a container-only type guard.",
        rationale="TypeGuard and TypeIs let callers trust their declared narrowing. Checking only dict, list, or set does not validate keys, values, or elements, so callers can perform operations that fail at runtime.",
        remediation="Use object for unchecked container slots, or validate their contents when the narrower contract is required. Keep constrained input types that already prove the contents.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks top-level, undecorated, non-generic synchronous functions with one positional parameter proven to be builtin object and a single return isinstance(parameter, builtin_container), optionally after a docstring.",
            "The TypeGuard or TypeIs target must be a matching builtin dict, list, or set whose slots all resolve to object, str, int, bool, float, or bytes; at least one slot must be narrower than object.",
            "Includes authored tests; generated and vendor source is excluded. String annotations, constrained input types, unions, Any, TypeVars, Protocols, assignment aliases, nested definitions, and content validators are not inferred.",
            "Annotation imports include TYPE_CHECKING imports. Runtime imports use conservative file-wide shadow facts, so unrelated local rebinding can cause false negatives. Wildcard imports, explicit writes to relevant builtin or typing attributes, and exception, pattern or walrus bindings that shadow relevant names or imported aliases exclude the file; dynamic namespace mutation is not inferred.",
            "Relative or conditional imports that replace relevant builtin or typing names exclude the file unless the import proves the same canonical symbol. Unrelated relative imports remain in scope.",
            "No autofix: widening the return contract can require caller changes, while adding content validation changes behavior and cost.",
        ),
        examples=(
            RuleExample(
                example_id="unchecked-dictionary-keys",
                title="A container check does not prove string keys",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/values.py", _BAD),),
                focus_path=PurePosixPath("app/values.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="honest-dictionary-keys",
                title="Unchecked keys retain their object type",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/values.py", _GOOD),),
                focus_path=PurePosixPath("app/values.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.tree is None or context.generated or _ambiguous_symbols(context):
            return []
        findings: list[Diagnostic] = []
        for function in context.tree.body:
            if not isinstance(function, ast.FunctionDef):
                continue
            statement = _shallow_guard(function, context)
            if statement is None or is_suppressed(context.source_lines, statement.lineno, self.code):
                continue
            findings.append(
                Diagnostic(
                    path=context.path,
                    line=statement.lineno,
                    col=statement.col_offset + 1,
                    code=self.code,
                    message="Container-only isinstance check does not validate the declared container contents; use object for unchecked slots or validate the contents required by the return type.",
                    severity=Severity.WARNING,
                )
            )
        return findings


def _shallow_guard(function: ast.FunctionDef, context: PythonFileContext) -> ast.Return | None:
    arguments = function.args
    positional = (*arguments.posonlyargs, *arguments.args)
    if function.decorator_list or function.type_params or len(positional) != 1:
        return None
    if arguments.kwonlyargs or arguments.vararg is not None or arguments.kwarg is not None:
        return None
    parameter = positional[0]
    if _builtin_symbol(parameter.annotation, context.module_imports) != "object":
        return None
    name = _guarded_container(function.returns, context.module_imports)
    if name is None:
        return None
    body = function.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    if len(body) != 1 or not isinstance(body[0], ast.Return):
        return None
    statement = body[0]
    call = statement.value
    if not isinstance(call, ast.Call) or call.keywords:
        return None
    match call.args:
        case [ast.Name(id=guarded_name), checked_container] if (
            guarded_name == parameter.arg
            and _builtin_symbol(call.func, context.imports) == "isinstance"
            and _builtin_symbol(checked_container, context.imports) == name
        ):
            return statement
        case _:
            return None


def _guarded_container(annotation: ast.expr | None, imports: ImportIndex) -> str | None:
    if not isinstance(annotation, ast.Subscript) or imports.resolved_symbol(
        annotation.value, sources=TYPING_SOURCES
    ) not in {"TypeGuard", "TypeIs"}:
        return None
    container = annotation.slice
    if not isinstance(container, ast.Subscript):
        return None
    name = _builtin_symbol(container.value, imports)
    if name not in _CONTAINERS:
        return None
    slots = container.slice.elts if isinstance(container.slice, ast.Tuple) else [container.slice]
    kinds = [_builtin_symbol(slot, imports) for slot in slots]
    if (
        len(kinds) != (_MAPPING_SLOTS if name == "dict" else 1)
        or any(kind not in _SLOTS for kind in kinds)
        or all(kind == "object" for kind in kinds)
    ):
        return None
    return name


def _builtin_symbol(node: ast.expr | None, imports: ImportIndex) -> str | None:
    if node is None:
        return None
    symbol = imports.resolved_symbol(node, sources=frozenset({"builtins"}))
    if symbol in _BUILTINS:
        return symbol
    if isinstance(node, ast.Name) and node.id in _BUILTINS and imports.builtin_is_unshadowed(node.id):
        return node.id
    return None


def _ambiguous_symbols(context: PythonFileContext) -> bool:
    sensitive_names = _BUILTINS | {
        name
        for name, target in context.module_imports.bindings.items()
        if target.module in TYPING_SOURCES | {"builtins"}
        and (target.symbol is None or target.symbol in _BUILTINS | {"TypeGuard", "TypeIs"})
    }
    for node in context.nodes(
        ast.Import,
        ast.ImportFrom,
        ast.Attribute,
        ast.ExceptHandler,
        ast.MatchAs,
        ast.MatchStar,
        ast.MatchMapping,
        ast.NamedExpr,
    ):
        match node:
            case ast.Import() | ast.ImportFrom():
                if _ambiguous_import(node, context.module_imports, sensitive_names):
                    return True
            case ast.Attribute(ctx=(ast.Store() | ast.Del())):
                if context.module_imports.resolved_qualified_name(node) in _MUTATION_TARGETS:
                    return True
            case (
                ast.ExceptHandler(name=name)
                | ast.MatchAs(name=name)
                | ast.MatchStar(name=name)
                | ast.MatchMapping(rest=name)
                | ast.NamedExpr(target=ast.Name(id=name))
            ):
                if name in sensitive_names:
                    return True
            case _:
                pass
    return False


def _ambiguous_import(node: ast.Import | ast.ImportFrom, imports: ImportIndex, sensitive_names: frozenset[str]) -> bool:
    if isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names):
        return True
    for alias in node.names:
        name = alias.asname or alias.name.partition(".")[0]
        if name not in sensitive_names:
            continue
        if not _preserves_canonical_import(node, alias, imports):
            return True
    return False


def _preserves_canonical_import(node: ast.Import | ast.ImportFrom, alias: ast.alias, imports: ImportIndex) -> bool:
    if isinstance(node, ast.ImportFrom):
        if node.level:
            return False
        module, symbol = node.module, alias.name
    else:
        module, symbol = alias.name, None
    name = alias.asname or alias.name.partition(".")[0]
    target = imports.bindings.get(name)
    if target is None:
        return module == "builtins" and symbol == name
    return target.module == module and target.symbol == symbol
