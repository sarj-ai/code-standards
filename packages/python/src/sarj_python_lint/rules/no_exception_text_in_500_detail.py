from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final, final, override

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
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules._route_shapes import http_status


if TYPE_CHECKING:
    from collections.abc import Mapping

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._imports import ImportIndex


_HTTP_EXCEPTION_MODULES: Final = frozenset({"fastapi", "fastapi.exceptions", "starlette.exceptions"})
_TRACEBACK_RENDERERS: Final = frozenset(
    {"format_exc", "format_exception", "format_exception_only", "format_tb", "format_stack"}
)
_TRACEBACK_MODULE: Final = frozenset({"traceback"})
_SERVER_ERROR: Final = 500
_MESSAGE = (
    "This HTTP 500 detail carries exception text, a traceback or a source path to the caller. Log the exception "
    "server-side and return a fixed message or error code."
)


@final
class NoExceptionTextIn500Detail(Rule):
    id = "no-exception-text-in-500-detail"
    code = "SARJ505"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="HTTP 500 exception details must not carry exception text or tracebacks.",
        rationale=(
            "An unexpected exception's text can contain SQL, file paths, hostnames, provider responses or personal "
            "data. Copying it into a 500 response discloses internals to any caller and gives attackers a probe."
        ),
        remediation="Log the exception with its traceback, then raise the 500 with a fixed detail or error code.",
        category=RuleCategory.SECURITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            (
                "Checks `HTTPException` from FastAPI or Starlette with a status resolved to 500 (integer, Starlette "
                "`status.HTTP_500_*` or `HTTPStatus.INTERNAL_SERVER_ERROR`)."
            ),
            (
                "The detail must use the variable bound by an enclosing `except ... as name` handler directly (not one "
                "of its attributes), call a `traceback.format_*` function, or reference `__file__`."
            ),
            (
                "Exception text copied first into another variable or model is not traced. Other statuses are not "
                "checked because 4xx details commonly map domain errors. Tests and generated files are excluded."
            ),
        ),
        examples=(
            RuleExample(
                example_id="exception-text",
                title="A 500 detail returns the exception message",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "api.py",
                        "from fastapi import HTTPException\n\n\ndef load(store) -> None:\n    try:\n"
                        "        store.load()\n    except Exception as exc:\n"
                        "        raise HTTPException(status_code=500, detail=f'load failed: {exc}') from exc\n",
                    ),
                ),
                focus_path=PurePosixPath("api.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="fixed-detail",
                title="A 500 detail is a fixed message",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "api.py",
                        "from fastapi import HTTPException\n\n\ndef load(store) -> None:\n    try:\n"
                        "        store.load()\n    except Exception as exc:\n"
                        "        raise HTTPException(status_code=500, detail='load failed') from exc\n",
                    ),
                ),
                focus_path=PurePosixPath("api.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.tree is None or context.generated or is_test_path(context.path):
            return []
        if "HTTPException" not in context.symbol_source:
            return []
        imports = context.imports
        return [
            Diagnostic(context.path, node.lineno, node.col_offset + 1, self.code, _MESSAGE, severity=Severity.WARNING)
            for node in context.nodes(ast.Call)
            if imports.resolved_symbol(node.func, sources=_HTTP_EXCEPTION_MODULES) == "HTTPException"
            and http_status(_argument(node, 0, "status_code")) == _SERVER_ERROR
            and _leaks(_argument(node, 1, "detail"), _handler_names(node, context.parents), imports, context.parents)
        ]


def _argument(call: ast.Call, position: int, name: str) -> ast.expr | None:
    keyword = next((keyword.value for keyword in call.keywords if keyword.arg == name), None)
    if keyword is not None:
        return keyword
    return call.args[position] if len(call.args) > position else None


def _handler_names(node: ast.AST, parents: Mapping[ast.AST, ast.AST]) -> frozenset[str]:
    names: set[str] = set()
    current = parents.get(node)
    while current is not None and not isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        if isinstance(current, ast.ExceptHandler) and current.name is not None:
            names.add(current.name)
        current = parents.get(current)
    return frozenset(names)


def _leaks(
    detail: ast.expr | None, handlers: frozenset[str], imports: ImportIndex, parents: Mapping[ast.AST, ast.AST]
) -> bool:
    if detail is None:
        return False
    for node in ast.walk(detail):
        match node:
            case ast.Name(id="__file__"):
                return True
            case ast.Name(id=name) if name in handlers and not isinstance(parents.get(node), ast.Attribute):
                return True
            case ast.Call(func=func) if (
                imports.resolved_symbol(func, sources=_TRACEBACK_MODULE) in _TRACEBACK_RENDERERS
            ):
                return True
            case _:
                pass
    return False
