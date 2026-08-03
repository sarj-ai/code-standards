"""SARJ017 — F-string passed as the message to a logging call

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_fstring_in_log.py
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._logging import LOG_METHODS, LOGGER_FACTORIES, is_logger_expr


if TYPE_CHECKING:
    from pathlib import Path


# Keyword arguments defined by stdlib `logging` (and never structured fields).
_STDLIB_FACTORY = "getLogger"

_STDLIB_ONLY_KWARGS = frozenset({"exc_info", "stack_info", "extra"})


class NoFstringInLog(Rule):
    id: str = "no-fstring-in-log"
    code: str = "SARJ017"
    description: str = (
        "f-string message in a logging call — pass variables as structured "
        "keyword arguments so logs stay filterable and templates stay constant."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        candidates = _candidates(tree)
        if not candidates:
            return []
        # Resolving the file's stdlib-`logging` bindings costs a second walk, so
        # only pay for it once something is actually at stake.
        stdlib = _StdlibLoggers.from_tree(tree)
        diags: list[Diagnostic] = []
        for node, offending in candidates:
            if not _is_stdlib_logging_call(node, stdlib):
                diags.append(
                    Diagnostic(
                        path=path,
                        line=offending.lineno,
                        col=offending.col_offset + 1,
                        code=self.code,
                        message=(
                            "f-string logging message — pass variables as keyword "
                            "arguments (logger.info('msg', key=value)) instead."
                        ),
                    )
                )
        return diags


def _candidates(tree: ast.Module) -> list[tuple[ast.Call, ast.JoinedStr]]:
    """Find every logging call whose message argument interpolates an f-string."""
    hits: list[tuple[ast.Call, ast.JoinedStr]] = []
    for node in nodes(tree, ast.Call):
        if not node.args or not _is_logging_call(node):
            continue
        offending = _interpolating_fstring(node.args[0])
        if offending is not None:
            hits.append((node, offending))
    return hits


def _is_logging_call(node: ast.Call) -> bool:
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in LOG_METHODS:
        return False
    return is_logger_expr(func.value)


class _StdlibLoggers:
    """The local names through which stdlib `logging` is reachable in one file."""

    def __init__(self) -> None:
        self.paths: set[str] = set()

    @classmethod
    def from_tree(cls, tree: ast.Module) -> _StdlibLoggers:
        """Collect every local binding that resolves to stdlib `logging`."""
        found = cls()
        for node in nodes(tree, ast.Import, ast.Assign, ast.AnnAssign):
            if isinstance(node, ast.Import):
                found._add_import(node)
            elif isinstance(node, ast.Assign):
                found._add_assignment(node.targets, node.value)
            elif node.value is not None:
                found._add_assignment([node.target], node.value)
        return found

    def _add_import(self, node: ast.Import) -> None:
        # `import logging` and `import logging.handlers` both bind `logging`.
        for alias in node.names:
            if alias.name == "logging" or alias.name.startswith("logging."):
                self.paths.add(alias.asname or "logging")

    def _add_assignment(self, targets: list[ast.expr], value: ast.expr) -> None:
        # `LOG = logging.getLogger(__name__)`, `self.logger = getLogger("x")`.
        if not _chain_has_getlogger(value):
            return
        for target in targets:
            path = _dotted_path(target)
            if path is not None:
                self.paths.add(".".join(path))

    def owns(self, receiver: ast.expr) -> bool:
        """Report whether `receiver` resolves to one of this file's stdlib bindings."""
        path = _dotted_path(receiver)
        if path is None:
            return False
        return any(".".join(path[: n + 1]) in self.paths for n in range(len(path)))


def _dotted_path(expr: ast.expr) -> list[str] | None:
    """Render `expr` as its dotted attribute path, descending through builder calls."""
    if isinstance(expr, ast.Name):
        return [expr.id]
    if isinstance(expr, ast.Attribute):
        base = _dotted_path(expr.value)
        return None if base is None else [*base, expr.attr]
    if isinstance(expr, ast.Call):
        return _dotted_path(expr.func)
    return None


def _is_stdlib_logging_call(node: ast.Call, stdlib: _StdlibLoggers) -> bool:
    """Report whether the call carries a stdlib-`logging` tell the loguru advice breaks."""
    if any(kw.arg in _STDLIB_ONLY_KWARGS for kw in node.keywords):
        return True
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    return _chain_has_getlogger(func.value) or stdlib.owns(func.value)


def _chain_has_getlogger(expr: ast.expr) -> bool:
    """Report whether a stdlib `logging` factory appears anywhere in the receiver chain."""
    node = expr
    while True:
        if isinstance(node, ast.Call):
            called = node.func
            # DOTTED callee: only the stdlib spelling counts.
            if isinstance(called, ast.Attribute) and called.attr == _STDLIB_FACTORY:
                return True
            # BARE callee: `get_logger()` and `getLogger()` are both ambiguous — the
            if isinstance(called, ast.Name) and called.id.lower() in LOGGER_FACTORIES:
                return True
            node = called
        elif isinstance(node, ast.Attribute):
            node = node.value
        else:
            return False


def _interpolating_fstring(node: ast.expr) -> ast.JoinedStr | None:
    """Find an interpolating f-string in `node`, descending `+`-concat operands."""
    if isinstance(node, ast.JoinedStr):
        return node if _has_interpolation(node) else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _interpolating_fstring(node.left) or _interpolating_fstring(node.right)
    return None


def _has_interpolation(node: ast.JoinedStr) -> bool:
    """Report whether the f-string actually interpolates a value (not just `f"literal"`)."""
    return any(isinstance(v, ast.FormattedValue) for v in node.values)
