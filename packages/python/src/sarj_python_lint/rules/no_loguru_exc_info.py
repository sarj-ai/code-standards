from __future__ import annotations

import ast
from pathlib import PurePosixPath
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
from sarj_python_lint.rules._imports import ambiguous_import_names as _ambiguous_import_names


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_METHODS = frozenset({"trace", "debug", "info", "success", "warning", "error", "critical", "log"})
_LOGURU = frozenset({"loguru"})


@final
class NoLoguruExcInfo(Rule):
    id = "no-loguru-exc-info"
    code = "SARJ508"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Loguru exc_info=True adds a field rather than retaining the exception traceback.",
        rationale=(
            "Loguru accepts logging keyword arguments as structured fields. The standard logging `exc_info=True` "
            "argument therefore does not attach an exception, leaving failure logs without their traceback."
        ),
        remediation="Use `logger.opt(exception=True)` or `logger.exception(...)` when reporting the active exception.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "Safe fixes handle only a direct proven Loguru logger call with literal arguments and keywords, replacing unused exc_info=True with opt(exception=True). Existing bind/opt chains, dynamic argument evaluation and commented calls remain review-only.",
            "Only unambiguous Loguru imports and immediate bind/opt chains with literal exc_info=True are checked.",
            "A literal message is required; templates using exc_info or the record, explicit exception capture, and exception() are excluded.",
            "Unknown receivers, stored logger aliases, dynamic exc_info values, ambiguous imports, and generated files are excluded.",
            "Runtime monkeypatches of Loguru objects or methods are not resolved.",
            "An intentionally stored field can use a diagnostic-specific suppression. More complex logging context remains review-only.",
        ),
        examples=(
            RuleExample(
                example_id="stdlib-argument-on-loguru",
                title="A standard logging argument does not capture the exception",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        'from loguru import logger\ntry:\n    int("invalid")\nexcept ValueError:\n    logger.warning("failed", exc_info=True)\n',
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="loguru-exception-option",
                title="Loguru captures the exception through opt",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        'from loguru import logger\ntry:\n    int("invalid")\nexcept ValueError:\n    logger.opt(exception=True).warning("failed")\n',
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="safe-autofix-subset",
                title="A proven subset has a convergent automatic fix",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        (
                            "from loguru import logger\n"
                            "try:\n"
                            "    action()\n"
                            "except ValueError:\n"
                            "    logger.warning('failed', exc_info=True)\n"
                        ),
                    ),
                ),
                fixed_files=(
                    ExampleFile.python(
                        "app/service.py",
                        (
                            "from loguru import logger\n"
                            "try:\n"
                            "    action()\n"
                            "except ValueError:\n"
                            "    logger.opt(exception=True).warning('failed')\n"
                        ),
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if "exc_info" not in context.symbol_source or context.generated or context.tree is None:
            return []
        shadowed = _ambiguous_import_names(context)
        if "*" in shadowed:
            return []
        diagnostics: list[Diagnostic] = []
        for call in context.nodes(ast.Call):
            if not isinstance(call.func, ast.Attribute) or call.func.attr not in _METHODS:
                continue
            keyword = next((item for item in call.keywords if item.arg == "exc_info"), None)
            if keyword is None or not isinstance(keyword.value, ast.Constant) or keyword.value.value is not True:
                continue
            if (
                not _is_unconfigured_loguru(call.func.value, context, shadowed)
                or not _has_unused_exc_info(call)
                or is_suppressed(context.source_lines, keyword.lineno, self.code)
            ):
                continue
            diagnostics.append(
                Diagnostic(
                    path=context.path,
                    line=keyword.lineno,
                    col=keyword.col_offset + 1,
                    code=self.code,
                    message="Loguru treats exc_info=True as a field; use opt(exception=True) or exception() to retain the traceback.",
                    severity=Severity.WARNING,
                ),
            )
        return diagnostics


def _is_unconfigured_loguru(receiver: ast.expr, context: PythonFileContext, shadowed: frozenset[str]) -> bool:
    opted = False
    while isinstance(receiver, ast.Call) and isinstance(receiver.func, ast.Attribute):
        method = receiver.func.attr
        if method not in {"bind", "opt"}:
            return False
        if method == "opt" and not opted:
            opted = True
            if any(
                keyword.arg is None
                or (
                    keyword.arg == "exception"
                    and not (isinstance(keyword.value, ast.Constant) and not keyword.value.value)
                )
                for keyword in receiver.keywords
            ):
                return False
        receiver = receiver.func.value
    root = receiver
    while isinstance(root, ast.Attribute):
        root = root.value
    return not (isinstance(root, ast.Name) and root.id in shadowed) and context.imports.resolves(
        receiver, sources=_LOGURU, symbol="logger"
    )


def _has_unused_exc_info(call: ast.Call) -> bool:
    message_index = int(isinstance(call.func, ast.Attribute) and call.func.attr == "log")
    message = (
        call.args[message_index]
        if len(call.args) > message_index
        else next((keyword.value for keyword in call.keywords if keyword.arg == "message"), None)
    )
    if not isinstance(message, ast.Constant) or not isinstance(message.value, str):
        return False
    return not _template_may_use_exc_info(message.value)


def _template_may_use_exc_info(template: str) -> bool:
    pending = [template]
    try:
        while pending:
            for _, field, spec, _ in Formatter().parse(pending.pop()):
                if field is not None:
                    if field.partition(".")[0].partition("[")[0] in {"exc_info", "record"}:
                        return True
                    if spec:
                        pending.append(spec)
    except ValueError:
        return True
    return False
