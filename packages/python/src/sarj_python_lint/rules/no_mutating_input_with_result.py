from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    ProjectRule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    is_suppressed,
)
from sarj_python_lint.rules._test_composition import direct_nodes


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_MAX_ALIAS_DEPTH = 8
_BAD = "from attrs import define\n@define\nclass Request:\n    expected_version: int\ndef send_update(body: Request) -> Response:\n    body.expected_version = 2\n    return send(body)\n"
_GOOD = "from attrs import define, evolve\n@define\nclass Request:\n    expected_version: int\ndef send_update(body: Request) -> Response:\n    updated = evolve(body, expected_version=2)\n    return send(updated)\n"


@final
class NoMutatingInputWithResult(ProjectRule):
    id = "no-mutating-input-with-result"
    code = "SARJ555"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Separate input attribute mutation from functions that return a result.",
        rationale="Returning an operation result can hide writes to a request object retained by the caller. Reusing that input then observes state changed by an earlier call.",
        remediation="Build and return a replacement input before sending it, or expose a deliberate in-place command returning None. Preserve response values and input contracts; do not discard the result to silence the rule.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks direct attribute assignments, augmented assignments and deletions through a parameter or an unambiguously assigned local alias in functions with an explicit non-None annotation and at least one value return. No class-name or model-library inference is needed.",
            "Pydantic writes and before-validator writes keep their existing SARJ481/SARJ482 owners. Builtin-container item mutation remains with SARJ520; this rule does not duplicate subscript diagnostics.",
            "None-returning commands, receiver state named self/cls, fresh copies, nested attributes, opaque mutator calls, generators, missing return annotations and unresolved or more than eight alias links are excluded.",
            "Intentional mutation-and-result APIs may retain a reasoned exact suppression. Warnings require review; no copying, return-type change or lifecycle rewrite is automatic.",
        ),
        examples=(
            RuleExample(
                example_id="attrs-request-mutated-before-response",
                title="Sending a generated request changes the caller's request",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("api.py", _BAD),),
                focus_path=PurePosixPath("api.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="attrs-request-replaced-before-response",
                title="Send a replacement and keep the input unchanged",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("api.py", _GOOD),),
                focus_path=PurePosixPath("api.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.tree is None or context.generated:
            return []
        owned = {mutation.node for mutation in context.copy_on_write.mutations}
        findings: list[Diagnostic] = []
        for function in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef):
            if not _returns_result(function, context):
                continue
            for target in _attribute_writes(function):
                if target in owned or is_suppressed(context.source_lines, target.lineno, self.code):
                    continue
                name = _input_owner(target.value, function, context)
                if name is not None:
                    findings.append(
                        Diagnostic(
                            context.path,
                            target.lineno,
                            target.col_offset + 1,
                            self.code,
                            f"This result-returning function also mutates input `{name}`; return a replacement or make the in-place command's None contract explicit.",
                            severity=Severity.WARNING,
                        )
                    )
        return findings


def _returns_result(function: ast.FunctionDef | ast.AsyncFunctionDef, context: PythonFileContext) -> bool:
    annotation = context.annotation_semantics.resolve_alias(function.returns)
    if annotation is None or (isinstance(annotation, ast.Constant) and annotation.value is None):
        return False
    nodes = tuple(direct_nodes(function))
    if any(isinstance(node, ast.Yield | ast.YieldFrom) for node in nodes):
        return False
    return any(
        isinstance(node, ast.Return)
        and node.value is not None
        and not (isinstance(node.value, ast.Constant) and node.value.value is None)
        for node in nodes
    )


def _attribute_writes(function: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[ast.Attribute, ...]:
    return tuple(
        node
        for node in direct_nodes(function)
        if isinstance(node, ast.Attribute)
        and isinstance(node.ctx, ast.Store | ast.Del)
        and isinstance(node.value, ast.Name)
    )


def _input_owner(
    expression: ast.expr,
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    context: PythonFileContext,
    depth: int = 0,
) -> str | None:
    if not isinstance(expression, ast.Name) or depth >= _MAX_ALIAS_DEPTH:
        return None
    binding = context.static_resource_provenance.binding(expression.id, expression)
    if isinstance(binding, ast.arg):
        arguments = (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
        return binding.arg if binding in arguments and binding.arg not in {"self", "cls"} else None
    if isinstance(binding, ast.Name):
        value = context.static_resource_provenance.assignment_value(binding, expression)
        if value is not None:
            return _input_owner(value, function, context, depth + 1)
    return None
