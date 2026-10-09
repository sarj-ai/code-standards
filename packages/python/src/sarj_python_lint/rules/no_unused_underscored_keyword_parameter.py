from __future__ import annotations

import ast
from itertools import chain
from pathlib import PurePosixPath
from types import MappingProxyType
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
from sarj_python_lint.rules._imports import ImportIndex


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


@final
class NoUnusedUnderscoredKeywordParameter(Rule):
    id = "no-unused-underscored-keyword-parameter"
    code = "SARJ475"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Remove unused underscore-prefixed keyword-only parameters instead of hiding them from lint.",
        rationale=(
            "A keyword-only parameter requires callers to use its declared name. Prefixing an unused input with an "
            "underscore silences unused-argument lint while retaining an input whose value has no effect. Removing "
            "the dead input and its callers keeps the callable's interface honest."
        ),
        remediation=(
            "Remove the unused keyword-only parameter and update callers together. If an external contract requires "
            "the input, preserve its required spelling and use a narrow, reasoned unused-argument suppression. "
            "Do not erase a precise callback signature with **kwargs or add dummy reads to silence this warning."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only underscore-prefixed keyword-only declarations are checked; positional and variadic callback slots are excluded.",
            "Decorated functions other than unshadowed builtin staticmethod/classmethod, inherited methods, and intentional stubs are excluded.",
            "Any reference within the body counts as use, including nested scopes; shadowing and reassignment can produce false negatives.",
            "Functions accessing locals, vars, eval, or exec through recognized builtin bindings are excluded.",
            "Callables referenced as values are excluded because their external keyword contract is unknown. Lambda parameters, unknown dynamic reflection, and cross-module callback contracts are not resolved.",
            "Generated and vendored files are excluded; test source is checked.",
        ),
        examples=(
            RuleExample(
                example_id="discarded-keyword-input",
                title="An ignored keyword input is kept just to silence unused-argument lint",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/sink.py", "def emit(*, _email=None):\n    return 'ready'\n"),),
                focus_path=PurePosixPath("app/sink.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="removed-keyword-input",
                title="The callable exposes only inputs it uses",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/sink.py", "def emit():\n    return 'ready'\n"),),
                focus_path=PurePosixPath("app/sink.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.generated or "_" not in context.source or context.tree is None:
            return []
        findings: list[Diagnostic] = []
        for function in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef):
            for argument in _unused_parameters(context, function):
                if is_suppressed(context.source_lines, argument.lineno, self.code):
                    continue
                findings.append(
                    Diagnostic(
                        path=context.path,
                        line=argument.lineno,
                        col=argument.col_offset + 1,
                        code=self.code,
                        severity=Severity.WARNING,
                        message=(
                            f"keyword-only parameter `{argument.arg}` is never referenced; remove the unused input "
                            "and its callers instead of hiding it from unused-argument lint"
                        ),
                    )
                )
        return sorted(findings, key=lambda item: (item.line, item.col))


def _unused_parameters(
    context: PythonFileContext, function: ast.FunctionDef | ast.AsyncFunctionDef
) -> tuple[ast.arg, ...]:
    candidates = [argument for argument in function.args.kwonlyargs if argument.arg.startswith("_")]
    if (
        not candidates
        or _has_contract(context, function)
        or _is_stub(function)
        or _escapes_as_callback(context, function)
    ):
        return ()
    body = list(chain.from_iterable(ast.walk(statement) for statement in function.body))
    if _reads_dynamic_locals(context, function, body):
        return ()
    references = {node.id for node in body if isinstance(node, ast.Name)}
    return tuple(argument for argument in candidates if argument.arg not in references)


def _has_contract(context: PythonFileContext, function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    parent = context.parents.get(function)
    while parent is not None and not isinstance(
        parent, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef | ast.Module
    ):
        parent = context.parents.get(parent)
    if isinstance(parent, ast.ClassDef) and parent.bases:
        return True
    return any(
        not (
            isinstance(decorator, ast.Name)
            and decorator.id in {"staticmethod", "classmethod"}
            and context.imports.builtin_is_unshadowed(decorator.id)
        )
        for decorator in function.decorator_list
    )


def _is_stub(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    body = function.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    if len(body) != 1:
        return False
    match body[0]:
        case ast.Pass() | ast.Return(value=None) | ast.Return(value=ast.Constant(value=None)):
            return True
        case ast.Expr(value=ast.Constant(value=value)):
            return value is Ellipsis
        case ast.Raise(exc=exception):
            if isinstance(exception, ast.Call):
                exception = exception.func
            return isinstance(exception, ast.Name) and exception.id == "NotImplementedError"
        case _:
            return False


def _reads_dynamic_locals(
    context: PythonFileContext, function: ast.FunctionDef | ast.AsyncFunctionDef, body: list[ast.AST]
) -> bool:
    local = ImportIndex.from_tree(ast.Module(body=[function, *function.body], type_ignores=[]))
    module = context.module_imports
    bindings = {name: target for name, target in module.bindings.items() if name not in local.shadowed_names}
    bindings.update(local.bindings)
    imports = ImportIndex(MappingProxyType(bindings), module.shadowed_names | local.shadowed_names)
    return any(
        isinstance(node, ast.expr)
        and (
            (
                isinstance(node, ast.Name)
                and node.id in {"locals", "vars", "eval", "exec"}
                and imports.builtin_is_unshadowed(node.id)
            )
            or imports.resolved_symbol(node, sources=frozenset({"builtins"})) in {"locals", "vars", "eval", "exec"}
        )
        for node in body
    )


def _escapes_as_callback(context: PythonFileContext, function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for reference in context.nodes(ast.Name, ast.Attribute):
        if (isinstance(reference, ast.Name) and reference.id != function.name) or (
            isinstance(reference, ast.Attribute) and reference.attr != function.name
        ):
            continue
        parent = context.parents.get(reference)
        if isinstance(reference.ctx, ast.Load) and not (isinstance(parent, ast.Call) and parent.func is reference):
            return True
    return False
