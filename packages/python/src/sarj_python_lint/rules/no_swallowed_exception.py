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
from sarj_python_lint.rules._logging import is_logger_expr
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path


if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._imports import ImportIndex

_RUFF_OWNED_BROAD_HANDLERS = frozenset({"Exception", "BaseException"})
_DELIBERATE_CONTROL_SIGNALS = frozenset(
    {
        "AttributeError",
        "FileExistsError",
        "FileNotFoundError",
        "GeneratorExit",
        "ImportError",
        "IndexError",
        "KeyError",
        "KeyboardInterrupt",
        "LookupError",
        "ModuleNotFoundError",
        "StopAsyncIteration",
        "StopIteration",
        "SystemExit",
    }
)


def _builtin_exception_names(root: type[BaseException]) -> Iterator[str]:
    yield root.__name__
    for child in root.__subclasses__():
        if child.__module__ == "builtins" and not child.__name__.startswith("_"):
            yield from _builtin_exception_names(child)


_BUILTIN_EXCEPTIONS = frozenset(_builtin_exception_names(BaseException))
_HIDDEN_LEVELS = frozenset({"debug", "trace"})
_MESSAGE = (
    "This handler records {caught} only at debug level and continues; let it propagate, return a typed failure, "
    "or log it at warning/error with the exception attached."
)

_SOURCE = """\
import logging

from google.api_core.exceptions import GoogleAPIError

logger = logging.getLogger(__name__)


def delete_object(store, path: str) -> None:
    try:
        store.delete(path=path)
    except (GoogleAPIError, OSError) as error:
{handler}
"""


@final
class NoSwallowedException(Rule):
    id = "no-swallowed-exception"
    code = "SARJ597"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Surface caught operational failures instead of recording them only at debug level.",
        rationale=(
            "A handler that catches a specific failure, writes it only to a debug or trace log and then continues "
            "makes the failure invisible: production log levels drop the record, the caller observes success and "
            "no traceback survives. Leaked resources and partial cleanups then go unnoticed."
        ),
        remediation=(
            "Let the error propagate, or handle it explicitly with a typed result the caller must inspect. For "
            "deliberate best-effort cleanup, record it at warning or error level with the exception attached, for "
            "example logger.exception(...), logger.warning(..., exc_info=True) or "
            "logger.opt(exception=error).warning(...)."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            (
                "Only handlers whose whole body is debug/trace logging, optionally with pass, an ellipsis, continue "
                "or a bare return from a function annotated -> None, are reported. A logging call with exc_info or "
                "a loguru opt(exception=...) receiver attaches the exception and is accepted. Info-level records "
                "and handlers without any log call are out of scope: on the evaluated corpora they were deliberate "
                "control flow such as fallbacks, retries and disconnects."
            ),
            (
                "Bare, Exception and BaseException handlers belong to Ruff BLE001, S110 and S112. CancelledError "
                "belongs to SARJ458. ImportError probes, process control, iteration protocol, expected lookups "
                "(KeyError, IndexError, LookupError, AttributeError, FileNotFoundError, FileExistsError) and "
                "exception classes defined in the same module are treated as deliberate signals."
            ),
            (
                "Exception types must be builtins or imported names; aliases, tuples bound to variables and dynamic "
                "expressions abstain. Logger receivers are recognised by name. contextlib.suppress, code after the "
                "try statement, tests, test support and generated files are not analysed."
            ),
        ),
        examples=(
            RuleExample(
                example_id="debug-only-cleanup",
                title="A cleanup failure is visible only at debug level",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "storage/cleanup.py",
                        _SOURCE.format(
                            handler='        logger.debug("cleanup unavailable", extra={"error": type(error).__name__})'
                        ),
                    ),
                ),
                focus_path=PurePosixPath("storage/cleanup.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="warning-with-traceback",
                title="Best-effort cleanup is recorded with the exception attached",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "storage/cleanup.py",
                        _SOURCE.format(handler='        logger.warning("cleanup failed", exc_info=error)'),
                    ),
                ),
                focus_path=PurePosixPath("storage/cleanup.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="propagate",
                title="The failure propagates to the owner",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "storage/cleanup.py",
                        "def delete_object(store, path: str) -> None:\n    store.delete(path=path)\n",
                    ),
                ),
                focus_path=PurePosixPath("storage/cleanup.py"),
                expected_count=0,
                public=False,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        source = context.symbol_source
        if "except" not in source or not ("debug" in source or "trace" in source):
            return []
        if context.generated or is_test_path(context.path) or is_test_support_path(context.path):
            return []
        tree = context.tree
        if tree is None or context.has_wildcard_import:
            return []
        local_classes = frozenset(node.name for node in tree.body if isinstance(node, ast.ClassDef))
        parents = context.parents
        diagnostics: list[Diagnostic] = []
        for node in context.nodes(ast.Try, ast.TryStar):
            for handler in node.handlers:
                caught = _caught_names(handler.type, context.imports, local_classes)
                if caught is None or not _hidden_body(
                    handler.body, _enclosing_function(node, parents), context.imports
                ):
                    continue
                if context.suppressions.is_suppressed(handler.lineno, self.code):
                    continue
                diagnostics.append(
                    Diagnostic(
                        path=context.path,
                        line=handler.lineno,
                        col=handler.col_offset + 1,
                        code=self.code,
                        message=_MESSAGE.format(caught=", ".join(caught)),
                        severity=Severity.WARNING,
                    )
                )
        return sorted(diagnostics, key=lambda item: (item.line, item.col))


def _caught_names(
    expression: ast.expr | None, imports: ImportIndex, local_classes: frozenset[str]
) -> tuple[str, ...] | None:
    match expression:
        case None:
            return None
        case ast.Tuple():
            elements = expression.elts
        case _:
            elements = [expression]
    names: list[str] = []
    for element in elements:
        if (name := _operational_failure(element, imports, local_classes)) is None:
            return None
        names.append(name)
    return tuple(names)


def _operational_failure(expression: ast.expr, imports: ImportIndex, local_classes: frozenset[str]) -> str | None:
    ignored = _RUFF_OWNED_BROAD_HANDLERS | _DELIBERATE_CONTROL_SIGNALS
    match expression:
        case ast.Name(id=name) if imports.builtin_is_unshadowed(name):
            return None if name in ignored or name not in _BUILTIN_EXCEPTIONS else name
        case ast.Name(id=name) if name in local_classes:
            return None
        case _:
            qualified = imports.resolved_qualified_name(expression)
            if qualified is None or qualified.rsplit(".", 1)[-1] in ignored | {"CancelledError"}:
                return None
            return ast.unparse(expression)


def _enclosing_function(
    node: ast.AST, parents: Mapping[ast.AST, ast.AST]
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    current = parents.get(node)
    while current is not None:
        match current:
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                return current
            case ast.ClassDef() | ast.Lambda():
                return None
            case _:
                current = parents.get(current)
    return None


def _hidden_body(
    body: list[ast.stmt], function: ast.FunctionDef | ast.AsyncFunctionDef | None, imports: ImportIndex
) -> bool:
    logged = False
    for statement in body:
        match statement:
            case ast.Pass() | ast.Continue() | ast.Expr(value=ast.Constant()):
                continue
            case ast.Return(value=None) | ast.Return(value=ast.Constant(value=None)) if _returns_none(function):
                continue
            case ast.Expr(value=ast.Call() as call) if _hidden_log(call, imports):
                logged = True
            case _:
                return False
    return logged


def _returns_none(function: ast.FunctionDef | ast.AsyncFunctionDef | None) -> bool:
    return function is not None and isinstance(function.returns, ast.Constant) and function.returns.value is None


def _hidden_log(call: ast.Call, imports: ImportIndex) -> bool:
    if not isinstance(call.func, ast.Attribute) or call.func.attr not in _HIDDEN_LEVELS:
        return False
    if any(keyword.arg is None or keyword.arg == "exc_info" for keyword in call.keywords):
        return False
    receiver = call.func.value
    while (
        isinstance(receiver, ast.Call)
        and isinstance(receiver.func, ast.Attribute)
        and receiver.func.attr in {"bind", "opt"}
    ):
        if any(keyword.arg is None or keyword.arg == "exception" for keyword in receiver.keywords):
            return False
        receiver = receiver.func.value
    return is_logger_expr(receiver) or imports.resolved_qualified_name(receiver) == "loguru.logger"
