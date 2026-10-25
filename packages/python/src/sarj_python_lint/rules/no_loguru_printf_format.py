from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
from string import Formatter
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


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._resource_provenance import ResourceProvenance


_METHODS = frozenset({"trace", "debug", "info", "success", "warning", "error", "critical", "exception", "log"})
_LOGURU = frozenset({"loguru"})
_CONVERSION = re.compile(r"%(?:\([^()]*\))?[-+ #0]*+(?:[0-9]+|\*)?(?:\.(?:[0-9]*|\*))?[hlL]?[diouxXeEfFgGcrsa]")


@final
class NoLoguruPrintfFormat(Rule):
    id = "no-loguru-printf-format"
    code = "SARJ509"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Use brace formatting for positional values passed to Loguru.",
        rationale=(
            "Loguru formats messages with str.format rather than printf interpolation. A percent-style message "
            "with positional values keeps its placeholders and loses the values from the rendered diagnostic."
        ),
        remediation=(
            "Use Loguru brace fields with equivalent formatting, or retain diagnostic values as named structured "
            "fields. Review numeric, mapping and width specifications rather than mechanically replacing percent signs."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "Safe fixes handle direct proven logger calls with a brace-free literal message, matching argument count and exact native primitive values. Only simple %s/%r/%a and integer-literal %d/%i fields are converted; widths, numeric coercion, mappings, custom values and logger chains remain review-only.",
            "Only unambiguous module-level Loguru imports and immediate bind/opt chains with a literal message and supplied positional formatting arguments are checked.",
            "The decoded literal message must contain a valid percent conversion and no brace fields; Unicode and hex escapes preserve conversions. Escaped percent signs alone, malformed templates, dynamic messages and expanded arguments are excluded.",
            "Standard logging, unknown receivers, stored aliases, shadowed or escaped imports, custom wrapper chains, keyword-only fields and generated files are excluded.",
            "Visible namespace or logger mutations invalidate import proof. Interprocedural effects and runtime monkeypatches are not resolved.",
            "Argument types and printf arity are not generally inferred. Only the explicitly proven primitive subset is fixed; other warnings require formatting/structured-field review.",
        ),
        examples=(
            RuleExample(
                example_id="safe-autofix-subset",
                title="Exact primitive arguments have an unambiguous brace format",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "from loguru import logger\nlogger.error('Request %s failed with status %d', 'marker', 503)\n",
                    ),
                ),
                fixed_files=(
                    ExampleFile.python(
                        "app/service.py",
                        "from loguru import logger\nlogger.error('Request {!s} failed with status {:d}', 'marker', 503)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
            ),
            RuleExample(
                example_id="printf-values-ignored",
                title="Loguru leaves printf placeholders unchanged",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        'from loguru import logger\nlogger.error("Request %s failed with status %d", "request-marker", 503)\n',
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="brace-values-rendered",
                title="Brace fields render positional diagnostic values",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        'from loguru import logger\nlogger.error("Request {} failed with status {}", "request-marker", 503)\n',
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if "loguru" not in context.symbol_source or context.generated or context.tree is None:
            return []
        provenance: ResourceProvenance | None = None
        diagnostics: list[Diagnostic] = []
        for call in context.nodes(ast.Call):
            if not isinstance(call.func, ast.Attribute) or call.func.attr not in _METHODS or not _printf_message(call):
                continue
            receiver = _logger_root(call.func.value)
            if receiver is None or not context.imports.resolves(receiver, sources=_LOGURU, symbol="logger"):
                continue
            if provenance is None:
                provenance = context.static_resource_provenance
                if not _logger_imports_untouched(context, provenance):
                    return []
            if not provenance.imported(receiver, "loguru.logger") or is_suppressed(
                context.source_lines, call.lineno, self.code
            ):
                continue
            diagnostics.append(
                Diagnostic(
                    path=context.path,
                    line=call.lineno,
                    col=call.col_offset + 1,
                    code=self.code,
                    message="Loguru leaves printf placeholders unchanged; use brace fields or named structured fields for these values.",
                    severity=Severity.WARNING,
                ),
            )
        return diagnostics


def _logger_imports_untouched(context: PythonFileContext, provenance: ResourceProvenance) -> bool:
    for node in context.nodes(ast.Name, ast.Attribute):
        qualified = context.imports.resolved_qualified_name(node)
        if qualified in {"loguru", "loguru.logger"} and not provenance.imported(node, qualified):
            return False
    return True


def _logger_root(receiver: ast.expr) -> ast.expr | None:
    while isinstance(receiver, ast.Call) and isinstance(receiver.func, ast.Attribute):
        if (
            receiver.func.attr not in {"bind", "opt"}
            or any(isinstance(argument, ast.Starred) for argument in receiver.args)
            or any(keyword.arg is None for keyword in receiver.keywords)
        ):
            return None
        receiver = receiver.func.value
    return receiver


def _printf_message(call: ast.Call) -> bool:
    index = int(isinstance(call.func, ast.Attribute) and call.func.attr == "log")
    if (
        len(call.args) <= index + 1
        or any(isinstance(argument, ast.Starred) for argument in call.args)
        or any(keyword.arg is None for keyword in call.keywords)
    ):
        return False
    message = call.args[index]
    if not isinstance(message, ast.Constant) or not isinstance(message.value, str):
        return False
    try:
        if any(field is not None for _, field, _, _ in Formatter().parse(message.value)):
            return False
    except ValueError:
        return False
    position = 0
    converted = False
    while (position := message.value.find("%", position)) != -1:
        if message.value.startswith("%%", position):
            position += 2
            continue
        token = _CONVERSION.match(message.value, position)
        if token is None:
            return False
        converted = True
        position = token.end()
    return converted
