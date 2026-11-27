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


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_HTTP_EXCEPTION_MODULES: Final = frozenset({"fastapi", "fastapi.exceptions", "starlette.exceptions"})
_MESSAGE = (
    "This service module raises `HTTPException`, which couples it to HTTP. Raise a domain exception and map it to a "
    "status in the router or an exception handler."
)
_SERVICE = "from fastapi import HTTPException\n\n\ndef cancel(order) -> None:\n    if order.shipped:\n"
_DOMAIN = "class OrderShippedError(Exception):\n    pass\n\n\ndef cancel(order) -> None:\n    if order.shipped:\n"


@final
class NoHttpExceptionInServices(Rule):
    id = "no-http-exception-in-services"
    code = "SARJ610"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Raise domain exceptions in service modules; map them to HTTP at the router.",
        rationale=(
            "A service that raises `HTTPException` fixes a status code for every caller, so workers, schedulers and "
            "other services that reuse it receive an HTTP error outside any request."
        ),
        remediation=(
            "Raise a domain exception from the service and convert it to a status in the router or a registered "
            "exception handler."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks modules below a directory named `services`; tests and generated files are excluded.",
            (
                "Reports a `raise` of FastAPI or Starlette `HTTPException` only. Subclasses, re-raised variables "
                "and `except HTTPException` handlers are not reported."
            ),
        ),
        examples=(
            RuleExample(
                example_id="service-raises-http-exception",
                title="A service raises an HTTP error",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/services/orders.py",
                        f"{_SERVICE}        raise HTTPException(status_code=409, detail='order_shipped')\n",
                    ),
                ),
                focus_path=PurePosixPath("app/services/orders.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="service-raises-domain-exception",
                title="A service raises a domain exception",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/services/orders.py", f"{_DOMAIN}        raise OrderShippedError\n"),),
                focus_path=PurePosixPath("app/services/orders.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if "services" not in context.path.parts[:-1] or "HTTPException" not in context.symbol_source:
            return []
        if context.tree is None or context.generated or is_test_path(context.path):
            return []
        imports = context.imports
        return [
            Diagnostic(context.path, node.lineno, node.col_offset + 1, self.code, _MESSAGE, severity=Severity.WARNING)
            for node in context.nodes(ast.Raise)
            if node.exc is not None
            and imports.resolves(
                node.exc.func if isinstance(node.exc, ast.Call) else node.exc,
                sources=_HTTP_EXCEPTION_MODULES,
                symbol="HTTPException",
            )
        ]
