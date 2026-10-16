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
from sarj_python_lint.rules._type_guard_symbols import (
    builtin_guard_symbol,
    guard_symbols_ambiguous,
    unique_guard_function_names,
)


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._imports import ImportIndex


_CONTAINERS = frozenset({"dict", "list", "set"})
_MAPPING_SLOTS = 2
_SLOTS = frozenset({"object", "str", "int", "bool", "float", "bytes"})
_BUILTINS = _SLOTS | _CONTAINERS | {"isinstance"}
_BAD = "from typing import TypeGuard\ndef is_mapping(value: object) -> TypeGuard[dict[str, object]]:\n    return isinstance(value, dict)\n"
_GOOD = _BAD.replace("dict[str, object]", "dict[object, object]")


@final
class NoShallowContainerTypeGuard(Rule):
    id = "no-shallow-container-type-guard"
    code = "SARJ472"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Do not claim typed container contents from a container-only type guard.",
        rationale="TypeGuard and TypeIs let callers trust their declared narrowing. Checking only dict, list, or set does not validate keys, values, or elements, so callers can perform operations that fail at runtime.",
        remediation="Use object for unchecked container slots, or validate their contents when the narrower contract is required. Keep constrained input types that already prove the contents.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks top-level, undecorated, non-generic synchronous functions with one positional parameter proven to be builtin object and a single return isinstance(parameter, builtin_container), optionally after a docstring.",
            "Repeated module-level function names abstain: an overload's public input contract can be narrower than the implementation annotation.",
            "The TypeGuard or TypeIs target must be a matching builtin dict, list, or set whose slots all resolve to object, str, int, bool, float, or bytes; at least one slot must be narrower than object.",
            "Includes authored tests; generated and vendor source is excluded. String annotations, constrained input types, unions, Any, TypeVars, Protocols, assignment aliases, nested definitions, and content validators are not inferred.",
            "Annotation imports include TYPE_CHECKING imports. Runtime imports use conservative file-wide shadow facts, so unrelated local rebinding can cause false negatives. Wildcard imports, explicit writes to relevant builtin or typing attributes, and exception, pattern or walrus bindings that shadow relevant names or imported aliases exclude the file; dynamic namespace mutation is not inferred.",
            "Relative or conditional imports that replace relevant builtin or typing names exclude the file unless the import proves the same canonical symbol. Unrelated relative imports remain in scope.",
            "No autofix: widening the return contract can require caller changes, while adding content validation changes behavior and cost.",
            "Visible __builtins__ access, canonical namespace-capability imports, module-class changes, and escaping typing/builtins module aliases abstain because namespace mutation can change the meaning of the check.",
            "Canonical native builtin function objects outside direct calls also abstain: captured, passed, or introspected function values can expose the mutable builtin namespace. The explicit native-function inventory covers CPython 3.14 and 3.15; unrelated application methods remain in scope, and arbitrary external effects are not inferred.",
            "Known native function names and canonical imported aliases remain possible namespace capabilities when shadowing or later rebinding obscures their identity. This conservatively excludes some benign first-class application variables with builtin function names.",
            "Direct __lazy_import__ calls and canonical aliases also abstain: CPython 3.15 introduces lazy imports that can return mutable module namespaces.",
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
        if (
            context.tree is None
            or context.generated
            or ("TypeGuard" not in context.symbol_source and "TypeIs" not in context.symbol_source)
            or _ambiguous_symbols(context)
        ):
            return []
        findings: list[Diagnostic] = []
        unique_names = unique_guard_function_names(context)
        for function in context.tree.body:
            if not isinstance(function, ast.FunctionDef) or function.name not in unique_names:
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
                    severity=Severity.ERROR,
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
    return builtin_guard_symbol(node, imports, _BUILTINS)


def _ambiguous_symbols(context: PythonFileContext) -> bool:
    return guard_symbols_ambiguous(context, _BUILTINS)
