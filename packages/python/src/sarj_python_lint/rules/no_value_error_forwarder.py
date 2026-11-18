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
from sarj_python_lint.rules._annotation_origins import AnnotationOrigins


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


@final
class NoValueErrorForwarder(Rule):
    id = "no-value-error-forwarder"
    code = "SARJ580"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Raise ValueError at the failure boundary instead of forwarding through a helper.",
        rationale="A helper that only forwards a message into ValueError hides the failure behind another call and stack frame without expressing a domain operation.",
        remediation="Review whether callers can raise ValueError directly. Preserve error messages, chaining and externally used callable contracts; shared error formatting can still deserve a helper.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks synchronous undecorated functions containing only a builtin ValueError raise with an unchanged message parameter or string literal. An optional docstring is allowed.",
            "Methods, decorated contracts, async functions, computed errors, explicit causes, variadic signatures and nonliteral defaults remain allowed. Requires a local direct call and no observed non-call reference; external consumers are not inferred.",
            "One warning per helper; generated, malformed and dynamically bound namespaces abstain. Review guidance does not imply duplicated raise sites are always preferable. There is no automatic inlining fix.",
        ),
        examples=(
            RuleExample(
                example_id="message-forwarder",
                title="A helper only forwards its message",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/parse.py", "def fail(message):\n    raise ValueError(message)\nfail('invalid input')\n"
                    ),
                ),
                focus_path=PurePosixPath("app/parse.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="failure-boundary",
                title="The failure stays at its owning boundary",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/parse.py",
                        "def parse(value):\n    if not value:\n        raise ValueError('invalid input')\n    return value\n",
                    ),
                ),
                focus_path=PurePosixPath("app/parse.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.generated or context.tree is None or "ValueError" not in context.symbol_source:
            return []
        facts = AnnotationOrigins(context)
        if facts.provenance.wildcard or facts.provenance.dynamic_namespace:
            return []
        return [
            Diagnostic(
                context.path,
                function.lineno,
                function.col_offset + 1,
                self.code,
                "This helper only raises ValueError with an unchanged message; review raising it directly at the failure boundary while preserving callable contracts.",
                severity=Severity.WARNING,
            )
            for function in context.nodes(ast.FunctionDef)
            if _forwarder(function, facts) and not context.suppressions.is_suppressed(function.lineno, self.code)
        ]


def _forwarder(function: ast.FunctionDef, facts: AnnotationOrigins) -> bool:
    if function.decorator_list or function.type_params or isinstance(facts.provenance.scope(function), ast.ClassDef):
        return False
    arguments = function.args
    if (
        arguments.vararg
        or arguments.kwarg
        or any(
            default is not None and not isinstance(default, ast.Constant)
            for default in (*arguments.defaults, *arguments.kw_defaults)
        )
    ):
        return False
    body = function.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    if len(body) != 1 or not isinstance(body[0], ast.Raise) or body[0].cause is not None:
        return False
    error = body[0].exc
    if not (
        isinstance(error, ast.Call)
        and len(error.args) == 1
        and not error.keywords
        and facts.builtin(error.func, "ValueError", error)
    ):
        return False
    message = error.args[0]
    parameters = {parameter.arg for parameter in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)}
    if not (
        (isinstance(message, ast.Name) and message.id in parameters)
        or (isinstance(message, ast.Constant) and isinstance(message.value, str))
    ):
        return False
    reads = facts.provenance.binding_reads(function.name, function)
    return bool(reads) and all(
        isinstance(parent := facts.context.parents.get(read), ast.Call) and parent.func is read for read in reads
    )
