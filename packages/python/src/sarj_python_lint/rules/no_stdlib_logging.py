"""SARJ052: stdlib `logging` imported in application code — the house logger is loguru.

Two logging systems in one process is one system too many. The stdlib logger
and loguru keep separate handler chains, separate levels and separate sinks, so
a module that reaches for `logging.getLogger(__name__)` writes to a logger
nobody configured: its records skip the JSON formatter, skip the Sentry
breadcrumb integration, skip the PII redaction patcher, and — because the
stdlib root logger defaults to WARNING with a `lastResort` stderr handler —
usually vanish in production while looking fine locally. The house convention
(`ruff.strict.toml` sets `logger-objects = ["loguru.logger"]` so ruff's G-family
even judges loguru calls) is that `from loguru import logger` is the only
logger.

Fires on any runtime import of the stdlib logging package:
`import logging`, `import logging as x`, `import logging.config`,
`from logging import getLogger`, `from logging.handlers import RotatingFileHandler`.

Deliberately NOT flagged:

* **the loguru bridge.** A module that imports stdlib `logging` *and* loguru is
  usually the shim that routes one into the other — an `InterceptHandler`
  subclassing `logging.Handler`, a `logging.basicConfig` call that installs it,
  a third-party library's logger being re-pointed. That is the one legitimate
  reason to touch stdlib logging in a loguru house. Measured across the two
  production corpora the exemption is exact: bulbul's three sites
  (`bulbul/__init__.py`, `configure_logging.py`, `agent/main.py`) and noura-be's
  one (`common/logging.py`) are all bridges, all import loguru, and no other
  module in either repo imports stdlib logging.

  Importing loguru is **not on its own** enough, though, and the first version of
  this rule made it so. A file-wide pass keyed on one import means that the day
  someone adds `import logging` + `logging.getLogger(__name__).info(...)` to a
  module that already says `from loguru import logger`, the rule goes quiet — and
  a module already using the house logger is the *most* likely place for a second
  hierarchy to appear by accident. So the exemption additionally requires the
  file to show that it **configures** stdlib logging rather than emitting through
  it: `logging.Handler` / `LogRecord` / `Logger` / `Formatter` / `Filter`,
  `basicConfig`, `addHandler` / `setLevel` / `addLevelName` / `handlers=` /
  `propagate`, `getLogger()` with no argument, or `logging.<LEVEL>` used as a
  level constant. All four production bridges match; a module that merely logs
  through both does not.
* **`if TYPE_CHECKING:` imports** — `logging.Logger` as an annotation is a type,
  not a logger. Nothing is emitted through it.
* **test files** (`_paths.is_test_path`) — `caplog` is pytest's fixture and it
  speaks stdlib logging; asserting on a dependency's records is normal.
* **`scripts/` and `notebooks/`** — one-shot code with no log pipeline to join.
* **generated files** — they mirror whatever their generator emits.

This is a house-convention rule, not a universal one: a *library* should log
through stdlib `logging` precisely because it must not impose a sink on its
callers (trio's three sites are correct for trio). Enable the hook in
applications, not in libraries.

A genuine exception is suppressed with `# sarj-noqa: SARJ052 — <reason>`.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes, walk
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_LOGGING_ROOT = "logging"
_LOGURU_ROOT = "loguru"

# Directories whose code is one-shot: no long-lived process, no log pipeline.
_EXEMPT_DIR_NAMES = frozenset({"scripts", "notebooks"})

# Evidence that a module CONFIGURES stdlib logging rather than emitting through
# it. Paired with a loguru import this is the bridge; a loguru import on its own
# is not, or the rule would fall silent on exactly the module most likely to grow
# a second logger hierarchy by accident.
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
    """Stdlib `logging` imported in application code — use loguru."""

    id: str = "no-stdlib-logging"
    code: str = "SARJ052"
    description: str = (
        "stdlib `logging` imported outside the loguru bridge — a second logger "
        "hierarchy with its own handlers, levels and sinks; use loguru."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Report every runtime stdlib-`logging` import in `source`.

        Returns:
            The diagnostics, sorted by (line, col).

        """
        if is_test_path(path) or _EXEMPT_DIR_NAMES.intersection(path.parts) or is_generated(path, source):
            return []
        # Every diagnostic comes from an `import logging...` statement, which
        # cannot exist unless the module name is spelled in the text. Checking
        # that first keeps the overwhelming majority of files from being parsed.
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
    """Collect every `import logging...` / `from logging... import ...` node.

    Returns:
        The importing nodes, one per statement, in source order.

    """
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
    """Report whether the module imports loguru anywhere.

    Half of the bridge test; the caller pairs it with `_BRIDGE_MARKER_RE` so that
    naming loguru is not on its own a licence to open a second logger hierarchy.

    Returns:
        True when loguru is imported.

    """
    if _LOGURU_ROOT not in source:
        return False
    return any(
        (isinstance(node, ast.Import) and any(_is_loguru_module(alias.name) for alias in node.names))
        or (isinstance(node, ast.ImportFrom) and node.module is not None and _is_loguru_module(node.module))
        for node in nodes(tree, ast.Import, ast.ImportFrom)
    )


def _type_checking_lines(tree: ast.Module, source: str) -> frozenset[int]:
    """Collect the line numbers of every statement guarded by `if TYPE_CHECKING:`.

    Returns:
        The 1-based lines that only exist for the type checker.

    """
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
    """Report whether `test` is the conventional `TYPE_CHECKING` guard.

    Returns:
        True for `TYPE_CHECKING` and `typing.TYPE_CHECKING`.

    """
    match test:
        case ast.Name(id="TYPE_CHECKING") | ast.Attribute(attr="TYPE_CHECKING"):
            return True
        case _:
            return False


def _is_logging_module(name: str) -> bool:
    """Report whether a dotted module name is stdlib `logging` or a submodule of it.

    Returns:
        True for `logging` and `logging.*`.

    """
    return name == _LOGGING_ROOT or name.startswith(f"{_LOGGING_ROOT}.")


def _is_loguru_module(name: str) -> bool:
    """Report whether a dotted module name is `loguru` or a submodule of it.

    Returns:
        True for `loguru` and `loguru.*`.

    """
    return name == _LOGURU_ROOT or name.startswith(f"{_LOGURU_ROOT}.")
