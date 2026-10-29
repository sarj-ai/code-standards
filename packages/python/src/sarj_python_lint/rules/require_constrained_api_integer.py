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
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


@final
class RequireConstrainedApiInteger(Rule):
    id = "require-constrained-api-integer"
    code = "SARJ553"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Declare numeric bounds for scalar integer FastAPI request parameters.",
        rationale="A bare integer request parameter accepts negative and arbitrarily large values even when the service expects a bounded page size or ordinal.",
        remediation="Use PositiveInt, NonNegativeInt or a domain Annotated type, or declare the appropriate Query/Path bounds. Keep signed and sentinel contracts explicit with a reasoned local exception.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks scalar builtin int annotations, optional unions and Annotated forms on source-proven FastAPI routes. Explicit bound metadata is accepted without guessing the intended minimum from a parameter name.",
            "Dependency/body/header/cookie injections, noninteger types, aliases, tests and generated sources are excluded. Query/Path defaults and Annotated metadata are recognized; cross-module aliases and custom validators are not interpreted.",
            "No automatic PositiveInt substitution is offered because zero, negative sentinels and signed domains need deliberate decisions.",
        ),
        examples=(
            RuleExample(
                example_id="unbounded-history-limit",
                title="The history API accepts any signed integer",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "api.py",
                        "from fastapi import APIRouter\nrouter = APIRouter()\n@router.get('/versions')\ndef versions(limit: int = 25):\n    return limit\n",
                    ),
                ),
                focus_path=PurePosixPath("api.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="positive-history-limit",
                title="Declare the valid numeric domain",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "api.py",
                        "from fastapi import APIRouter\nfrom pydantic import PositiveInt\nrouter = APIRouter()\n@router.get('/versions')\ndef versions(limit: PositiveInt = 25):\n    return limit\n",
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
        findings: list[Diagnostic] = []
        for node in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef):
            if not context.fastapi.routes(node):
                continue
            args = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
            defaults = _argument_defaults(node)
            for arg in args:
                if not _unbounded_request_argument(arg, defaults.get(arg.arg), context) or is_suppressed(
                    context.source_lines, arg.lineno, self.code
                ):
                    continue
                findings.append(
                    Diagnostic(
                        context.path,
                        arg.lineno,
                        arg.col_offset + 1,
                        self.code,
                        "Declare the valid numeric domain for this integer request parameter with a constrained type or Query/Path bounds.",
                        severity=Severity.WARNING,
                    )
                )
        return findings


def _argument_defaults(function: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, ast.expr]:
    positional = (*function.args.posonlyargs, *function.args.args)
    defaults = {
        argument.arg: value
        for argument, value in zip(
            positional[len(positional) - len(function.args.defaults) :], function.args.defaults, strict=True
        )
    }
    defaults.update(
        {
            argument.arg: value
            for argument, value in zip(function.args.kwonlyargs, function.args.kw_defaults, strict=True)
            if value is not None
        }
    )
    return defaults


def _unbounded_request_argument(argument: ast.arg, default: ast.expr | None, context: PythonFileContext) -> bool:
    if not _bare_integer(argument.annotation, context):
        return False
    expressions = [part for part in (argument.annotation, default) if part is not None]
    return not any(_constraint_or_injection(part, context) for part in expressions)


def _bare_integer(annotation: ast.expr | None, context: PythonFileContext) -> bool:
    match annotation:
        case ast.Name(id="int"):
            return context.module_imports.builtin_is_unshadowed("int")
        case ast.BinOp(left=left, op=ast.BitOr(), right=right):
            return (_bare_integer(left, context) and _none_annotation(right)) or (
                _none_annotation(left) and _bare_integer(right, context)
            )
        case ast.Subscript(value=value, slice=inner) if context.module_imports.resolves(
            value, sources=frozenset({"typing", "typing_extensions"}), symbol="Optional"
        ):
            return _bare_integer(inner, context)
        case ast.Subscript(value=value, slice=ast.Tuple(elts=elements)) if context.module_imports.resolves(
            value, sources=frozenset({"typing", "typing_extensions"}), symbol="Annotated"
        ):
            return bool(elements) and _bare_integer(elements[0], context)
        case _:
            return False


def _none_annotation(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _constraint_or_injection(node: ast.expr, context: PythonFileContext) -> bool:
    imports = context.module_imports
    for item in ast.walk(node):
        if not isinstance(item, ast.Call):
            continue
        if any(
            imports.resolves(item.func, sources=frozenset({"fastapi", "fastapi.params"}), symbol=name)
            for name in ("Depends", "Security", "Body", "Header", "Cookie", "Form", "File")
        ):
            return True
        if any(
            imports.resolves(item.func, sources=frozenset({"annotated_types"}), symbol=name)
            for name in ("Ge", "Gt", "Le", "Lt")
        ):
            return True
        if any(
            imports.resolves(
                item.func, sources=frozenset({"fastapi", "fastapi.params", "pydantic", "pydantic.fields"}), symbol=name
            )
            for name in ("Query", "Path", "Field")
        ) and any(
            keyword.arg in {"ge", "gt", "le", "lt"}
            and not (isinstance(keyword.value, ast.Constant) and keyword.value.value is None)
            for keyword in item.keywords
        ):
            return True
    return False
