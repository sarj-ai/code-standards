"""SARJ052 — Stdlib `logging` imported in application code — the house logger is loguru.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_stdlib_logging.py
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import nodes, walk
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_LOGGING_ROOT = "logging"
_LOGURU_ROOT = "loguru"

# Directories whose code is one-shot: no long-lived process, no log pipeline.
_EXEMPT_DIR_NAMES = frozenset({"scripts", "notebooks"})

# Configuration modules may bridge stdlib logging without using it as the application logger.
_BRIDGE_MARKER_RE = re.compile(
    r"\b(?:Handler|LogRecord|Logger|Formatter|Filter|LoggerAdapter|LoggingIntegration)\b|"
    r"\b(?:basicConfig|addHandler|removeHandler|setLevel|addLevelName|addFilter|dictConfig|fileConfig|captureWarnings|lastResort)\b|"
    r"\bpropagate\b|\bhandlers\s*=|"
    r"\bgetLogger\s*\(\s*\)|"
    r"\blogging\.(?:DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL|NOTSET)\b"
)

_MESSAGE = (
    "stdlib `logging` is not the house logger — use `from loguru import logger`. "
    "Two logger hierarchies means separate handlers, levels and sinks, so these "
    "records skip the configured formatter, redaction and error reporting."
)


@final
class NoStdlibLogging(Rule):
    id: str = "no-stdlib-logging"
    code: str = "SARJ052"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Application code imports standard-library logging instead of the configured house logger.",
        rationale="Parallel logger hierarchies can bypass shared formatting, redaction, levels, sinks, and error reporting.",
        remediation="Import the configured loguru logger; keep stdlib logging only in the explicit bridge module.",
        category=RuleCategory.ARCHITECTURE,
        limitations=(
            "Tests, scripts, notebooks, generated files, type-only imports, and recognized loguru bridge configuration are excluded.",
            "Detection reports imports of the standard-library logging root, not similarly named first-party modules.",
        ),
        examples=(
            RuleExample(
                example_id="stdlib-logging-import",
                title="Application imports stdlib logging",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python("app/service.py", "import logging\n\nlogger = logging.getLogger(__name__)\n"),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="house-logger-import",
                title="Application imports loguru",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/service.py", "from loguru import logger\n"),),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Report every runtime stdlib-`logging` import in `source`."""
        if is_test_path(path) or _EXEMPT_DIR_NAMES.intersection(path.parts) or is_generated(path, source):
            return []
        # Skip parsing unless the only import root this rule reports is present.
        if _LOGGING_ROOT not in source:
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        if _imports_loguru(tree, source) and _BRIDGE_MARKER_RE.search(source):
            return []
        imports = _logging_imports(tree)
        if not imports:
            return []
        # Only worth locating the type-only statements once something can be reported.
        type_only = _type_checking_lines(tree, source)
        diags = [
            Diagnostic(
                path=path,
                line=line,
                col=node.col_offset + 1,
                code=self.code,
                message=_MESSAGE,
            )
            for node in imports
            if (line := node.lineno) not in type_only
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _logging_imports(tree: ast.Module) -> list[ast.Import | ast.ImportFrom]:
    """Collect every `import logging...` / `from logging... import ...` node."""
    out: list[ast.Import | ast.ImportFrom] = []
    for node in nodes(tree, ast.Import, ast.ImportFrom):
        match node:
            case ast.Import(names=names) if any(_is_logging_module(alias.name) for alias in names):
                out.append(node)
            case ast.ImportFrom(module=str(module), level=0) if _is_logging_module(module):
                out.append(node)
            case _:
                pass
    return out


def _imports_loguru(tree: ast.Module, source: str) -> bool:
    """Report whether the module imports loguru anywhere."""
    if _LOGURU_ROOT not in source:
        return False
    return any(
        (isinstance(node, ast.Import) and any(_is_loguru_module(alias.name) for alias in node.names))
        or (isinstance(node, ast.ImportFrom) and node.module is not None and _is_loguru_module(node.module))
        for node in nodes(tree, ast.Import, ast.ImportFrom)
    )


def _type_checking_lines(tree: ast.Module, source: str) -> frozenset[int]:
    """Collect the line numbers of every statement guarded by `if TYPE_CHECKING:`."""
    if "TYPE_CHECKING" not in source:
        return frozenset()
    return frozenset(
        inner.lineno
        for node in nodes(tree, ast.If)
        if _is_type_checking_test(node.test)
        for stmt in node.body
        for inner in walk(stmt)
        if isinstance(inner, ast.stmt)
    )


def _is_type_checking_test(test: ast.expr) -> bool:
    """Report whether `test` is the conventional `TYPE_CHECKING` guard."""
    match test:
        case ast.Name(id="TYPE_CHECKING") | ast.Attribute(attr="TYPE_CHECKING"):
            return True
        case _:
            return False


def _is_logging_module(name: str) -> bool:
    """Report whether a dotted module name is stdlib `logging` or a submodule of it."""
    return name == _LOGGING_ROOT or name.startswith(f"{_LOGGING_ROOT}.")


def _is_loguru_module(name: str) -> bool:
    """Report whether a dotted module name is `loguru` or a submodule of it."""
    return name == _LOGURU_ROOT or name.startswith(f"{_LOGURU_ROOT}.")
