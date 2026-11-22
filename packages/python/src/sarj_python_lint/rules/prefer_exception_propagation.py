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

_GENERIC_ERRORS = ("Exception", "RuntimeError", "ValueError", "TypeError", "SystemExit")
_MESSAGE_AND_RAISE = 2


@final
class PreferExceptionPropagation(Rule):
    id = "prefer-exception-propagation"
    code = "SARJ585"
    documentation = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Propagate exceptions instead of replacing them with message-only generic errors.",
        rationale=(
            "Catching an exception only to copy its text into a generic error loses the original error type "
            "and adds a handler without recovery or additional context. Callers then cannot classify the original failure."
        ),
        remediation=(
            "Remove the message-only handler and let the original exception propagate. Preserve "
            "intentional public exception contracts, privacy, retries and cleanup. Keep an explained exact-code "
            "exception when the generic exception type is an intentional boundary contract."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Changing an exception type can affect callers, so no automatic rewrite is offered.",
            (
                "Checks handlers that only raise builtin Exception, RuntimeError, ValueError, TypeError or SystemExit "
                "with a constant message, str(caught_error) or an equivalent single-field f-string, optionally through "
                "one local message assignment. Explicit from None does not justify an otherwise redundant wrapper. "
                "Bare rethrows belong to Ruff TRY201/TRY203."
            ),
            (
                "Additional context or formatting, custom exception types, keyword metadata, logging, retries and "
                "other handler statements remain allowed. Finally blocks must remain when removing a redundant handler. "
                "A required generic public/privacy boundary needs an exact-code justified exception. Shadowed builtins, "
                "dynamic bindings, generated and malformed files abstain."
            ),
        ),
        examples=(
            RuleExample(
                example_id="constant-cli-replacement",
                scenario="constant-replacement",
                title="A generic CLI replacement hides the original failure",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/send.py",
                        "try:\n    send()\nexcept (OSError, ValueError):\n    message = 'Request failed'\n    raise SystemExit(message) from None\n",
                    ),
                ),
                focus_path=PurePosixPath("app/send.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="unwrapped-failure",
                scenario="constant-replacement",
                title="The original failure retains its type and context",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/send.py", "send()\n"),),
                focus_path=PurePosixPath("app/send.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="message-only-wrapper",
                title="The wrapper only copies the original message",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/send.py",
                        "try:\n    send()\nexcept Exception as error:\n    raise RuntimeError(str(error)) from error\n",
                    ),
                ),
                focus_path=PurePosixPath("app/send.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="propagate",
                title="Let the original exception reach its owner",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/send.py", "send()\n"),),
                focus_path=PurePosixPath("app/send.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="privacy-boundary",
                title="A privacy boundary deliberately sanitizes the failure",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/send.py",
                        "try:\n    send()\nexcept ProviderError:\n    raise TaskFailureError('Provider failed', retriable=True) from None\n",
                    ),
                ),
                focus_path=PurePosixPath("app/send.py"),
                expected_count=0,
                public=False,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.generated or context.tree is None or "except" not in context.symbol_source:
            return []
        facts = AnnotationOrigins(context)
        if facts.provenance.wildcard or facts.provenance.dynamic_namespace:
            return []
        return [
            Diagnostic(
                context.path,
                handler.lineno,
                handler.col_offset + 1,
                self.code,
                "This handler only replaces the failure with a generic message; let the original exception propagate. "
                "Preserve cleanup and use an exact-code exception for a required public/privacy boundary.",
                severity=Severity.ERROR,
            )
            for node in context.nodes(ast.Try, ast.TryStar)
            for handler in node.handlers
            if _message_only_wrapper(handler, facts) and not _suppressed_header(handler, context)
        ]


def _suppressed_header(handler: ast.ExceptHandler, context: PythonFileContext) -> bool:
    stop = max(handler.lineno + 1, handler.body[0].lineno)
    return any(context.suppressions.is_suppressed(line, "SARJ585") for line in range(handler.lineno, stop))


def _message_only_wrapper(handler: ast.ExceptHandler, facts: AnnotationOrigins) -> bool:
    if handler.type is None:
        return False
    body = handler.body
    if not 1 <= len(body) <= _MESSAGE_AND_RAISE:
        return False
    last = body[-1]
    if not isinstance(last, ast.Raise):
        return False
    if last.cause is not None and not (
        (isinstance(last.cause, ast.Constant) and last.cause.value is None)
        or (isinstance(last.cause, ast.Name) and last.cause.id == handler.name)
    ):
        return False
    error = last.exc
    if not isinstance(error, ast.Call) or len(error.args) != 1 or error.keywords:
        return False
    if not any(
        facts.builtin(error.func, name, error) or facts.qualified(error.func, error) == f"builtins.{name}"
        for name in _GENERIC_ERRORS
    ):
        return False
    argument = _message_argument(body, error.args[0], handler.name)
    return argument is not None and (
        (isinstance(argument, ast.Constant) and isinstance(argument.value, str))
        or (handler.name is not None and _caught_message(argument, handler.name, facts))
    )


def _message_argument(body: list[ast.stmt], argument: ast.expr, caught: str | None) -> ast.expr | None:
    if len(body) == 1:
        return argument
    assignment = body[0]
    if not isinstance(assignment, ast.Assign) or len(assignment.targets) != 1:
        return None
    target = assignment.targets[0]
    if not isinstance(target, ast.Name) or target.id == caught:
        return None
    if not isinstance(argument, ast.Name) or argument.id != target.id:
        return None
    return assignment.value


def _caught_message(expression: ast.expr, caught: str, facts: AnnotationOrigins) -> bool:
    if isinstance(expression, ast.Call):
        return (
            facts.builtin(expression.func, "str", expression)
            and len(expression.args) == 1
            and not expression.keywords
            and isinstance(expression.args[0], ast.Name)
            and expression.args[0].id == caught
        )
    if not isinstance(expression, ast.JoinedStr) or len(expression.values) != 1:
        return False
    field = expression.values[0]
    return (
        isinstance(field, ast.FormattedValue)
        and field.conversion in {-1, ord("s")}
        and field.format_spec is None
        and isinstance(field.value, ast.Name)
        and field.value.id == caught
    )
