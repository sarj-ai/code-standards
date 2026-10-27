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
    is_suppressed,
)
from sarj_python_lint.rules._numeric_proof import (
    assignment,
    function_body,
    imported_api,
    local_function,
    native_builtin,
    null_test,
    overridden_exit,
    returns_none,
)
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_PROBE_BODY_LENGTH = 2
_FALLBACK_OPERANDS = 2
_PROBE = """import subprocess

def read_status():
    try:
        result = subprocess.run(["service", "status"], capture_output=True, text=True, check=False)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return None if result.returncode else result.stdout

def active_count():
    output = read_status()
    return None if output is None else output.count("active")

"""
_BAD = (
    _PROBE
    + """def recovered(baseline: int) -> bool:
    if (active_count() or 0) >= baseline:
        return True
    return False
"""
)
_GOOD = (
    _PROBE
    + """def recovered(baseline: int) -> bool:
    observed = active_count()
    if observed is not None and observed >= baseline:
        return True
    return False
"""
)


@final
class FailedProbeZeroThreshold(Rule):
    id = "failed-probe-zero-threshold"
    code = "SARJ538"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Do not let a failed subprocess count probe meet its threshold through a zero fallback.",
        rationale="A failed observation is different from an observed count of zero. Coalescing the error sentinel can make a recovery comparison succeed when its baseline is zero.",
        remediation="Check the probe result for None before comparing it, or make an intentional zero-baseline skip policy explicit.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Recognizes an undecorated same-module synchronous subprocess.run text probe returning None on failure/nonzero status, followed by one local str.count wrapper preserving None.",
            "The initial sink is a direct if comparison of (count_probe() or 0) >= a literal zero or an int-typed parameter, with a terminal True return or a None return before a proven local raising failure helper.",
            "Known zero-baseline skip policies, other parameter validation/uses before the comparison, unknown aliases, reassignment, escaping helpers, reflection, test/generated files, and dynamic imports abstain. Control-transferring enclosing finalizers also abstain. Function and variable names do not establish probe intent.",
            "Async command wrappers, imported helpers, deeper interprocedural count parsing, compound success conditions and dynamically constrained thresholds are not inferred. This warning identifies an error-derived accepted sentinel; it does not prove every surrounding health check failed.",
        ),
        examples=(
            RuleExample(
                example_id="failed-probe-accepted-as-zero",
                title="Keep failed observation distinct from zero",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/recovery.py", _BAD),),
                focus_path=PurePosixPath("app/recovery.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="failed-probe-rejected",
                title="Reject a missing observation explicitly",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/recovery.py", _GOOD),),
                focus_path=PurePosixPath("app/recovery.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if (
            "returncode" not in context.symbol_source
            or "count" not in context.symbol_source
            or context.generated
            or is_test_path(context.path)
        ):
            return []
        if context.tree is None or context.dynamic_namespace or context.has_wildcard_import:
            return []
        findings: list[Diagnostic] = []
        for branch in context.nodes(ast.If):
            fallback = _accepted_failure_fallback(context, branch)
            if fallback is None:
                continue
            if is_suppressed(context.source_lines, fallback.lineno, self.code):
                continue
            findings.append(
                Diagnostic(
                    path=context.path,
                    line=fallback.lineno,
                    col=fallback.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message="this subprocess probe's error-derived None becomes zero and can satisfy the recovery comparison; reject None explicitly or declare the zero-baseline skip policy",
                )
            )
        return findings


def _accepted_failure_fallback(context: PythonFileContext, branch: ast.If) -> ast.BoolOp | None:
    test = branch.test
    if overridden_exit(context, branch):
        return None
    if not isinstance(test, ast.Compare) or len(test.ops) != 1 or not isinstance(test.ops[0], ast.GtE):
        return None
    fallback = test.left
    if (
        not isinstance(fallback, ast.BoolOp)
        or not isinstance(fallback.op, ast.Or)
        or len(fallback.values) != _FALLBACK_OPERANDS
    ):
        return None
    probe, sentinel = fallback.values
    if not isinstance(sentinel, ast.Constant) or type(sentinel.value) is not int or sentinel.value != 0:
        return None
    if not isinstance(probe, ast.Call) or not _count_probe(context, probe):
        return None
    owner = context.static_resource_provenance.scope(test)
    if not isinstance(owner, ast.FunctionDef) or not _successful_return(context, owner, branch):
        return None
    if not _zero_threshold(context, test.comparators[0], owner):
        return None
    return fallback


def _count_probe(context: PythonFileContext, call: ast.Call) -> bool:
    function = local_function(context, call.func)
    if function is None or call.args or call.keywords:
        return False
    body = function_body(function)
    if len(body) != _PROBE_BODY_LENGTH or (bound := assignment(body[0])) is None or not isinstance(body[1], ast.Return):
        return False
    name = bound.target
    source = bound.value
    if not isinstance(source, ast.Call) or not _text_probe(context, source):
        return False
    result = body[1].value
    return (
        isinstance(result, ast.IfExp)
        and null_test(result.test, name.id)
        and isinstance(result.body, ast.Constant)
        and result.body.value is None
        and isinstance(result.orelse, ast.Call)
        and not result.orelse.keywords
        and len(result.orelse.args) == 1
        and isinstance(result.orelse.func, ast.Attribute)
        and result.orelse.func.attr == "count"
        and isinstance(result.orelse.func.value, ast.Name)
        and result.orelse.func.value.id == name.id
        and context.static_resource_provenance.binding(name.id, result.orelse.func.value) is name
    )


def _text_probe(context: PythonFileContext, call: ast.Call) -> bool:
    function = local_function(context, call.func)
    if function is None:
        return False
    body = function_body(function)
    if len(body) != _PROBE_BODY_LENGTH or not isinstance(body[0], ast.Try) or not isinstance(body[1], ast.Return):
        return False
    attempt = body[0]
    if attempt.orelse or attempt.finalbody or len(attempt.body) != 1 or not attempt.handlers:
        return False
    bound = assignment(attempt.body[0])
    if bound is None:
        return False
    name = bound.target
    source = bound.value
    if not isinstance(source, ast.Call) or not imported_api(context, source.func, "subprocess.run"):
        return False
    keywords = {item.arg: item.value for item in source.keywords}
    if None in keywords or not all(
        isinstance(value_node := keywords.get(key), ast.Constant) and value_node.value is value
        for key, value in (("capture_output", True), ("text", True), ("check", False))
    ):
        return False
    if not all(_error_handler(context, handler) for handler in attempt.handlers):
        return False
    result = body[1].value
    return (
        isinstance(result, ast.IfExp)
        and _result_member(result.test, name.id, "returncode")
        and isinstance(result.body, ast.Constant)
        and result.body.value is None
        and _result_member(result.orelse, name.id, "stdout")
        and len(context.static_resource_provenance.bindings.get(function, {}).get(name.id, ())) == 1
    )


def _error_handler(context: PythonFileContext, handler: ast.ExceptHandler) -> bool:
    if handler.type is None or len(handler.body) != 1 or not returns_none(handler.body[0]):
        return False
    kinds = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return all(
        native_builtin(context, kind, "OSError")
        or context.imports.resolved_qualified_name(kind) == "subprocess.TimeoutExpired"
        for kind in kinds
    )


def _result_member(expression: ast.expr, name: str, member: str) -> bool:
    return (
        isinstance(expression, ast.Attribute)
        and expression.attr == member
        and isinstance(expression.value, ast.Name)
        and expression.value.id == name
    )


def _zero_threshold(context: PythonFileContext, expression: ast.expr, owner: ast.FunctionDef) -> bool:
    if isinstance(expression, ast.Constant):
        return type(expression.value) is int and expression.value == 0
    if not isinstance(expression, ast.Name):
        return False
    provenance = context.static_resource_provenance
    binding = provenance.binding(expression.id, expression)
    if not isinstance(binding, ast.arg) or provenance.scope(binding) is not owner:
        return False
    annotation = binding.annotation
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        annotation = (
            annotation.left if isinstance(annotation.right, ast.Constant) and annotation.right.value is None else None
        )
    if not isinstance(annotation, ast.Name) or not native_builtin(context, annotation, "int"):
        return False
    for read in provenance.binding_reads(expression.id, binding):
        if read.lineno >= expression.lineno:
            continue
        parent = context.parents.get(read)
        if not isinstance(parent, ast.Compare) or not null_test(parent, expression.id):
            return False
    return True


def _successful_return(context: PythonFileContext, owner: ast.FunctionDef, branch: ast.If) -> bool:
    if len(branch.body) != 1 or branch.orelse or not isinstance(branch.body[0], ast.Return):
        return False
    result = branch.body[0]
    if isinstance(result.value, ast.Constant) and result.value.value is True:
        return True
    if not returns_none(result) or not isinstance(owner.returns, ast.Constant) or owner.returns.value is not None:
        return False
    tail = owner.body[-1]
    if not isinstance(tail, ast.Expr) or not isinstance(tail.value, ast.Call):
        return False
    failure = local_function(context, tail.value.func)
    return failure is not None and len(function_body(failure)) == 1 and isinstance(function_body(failure)[0], ast.Raise)
