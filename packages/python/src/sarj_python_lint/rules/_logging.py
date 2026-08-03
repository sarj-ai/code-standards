"""Shared logging-receiver detection for SARJ012/SARJ017."""

from __future__ import annotations

import ast


_LOGGER_NAMES = frozenset({"logger", "log", "logging", "loguru", "_logger", "_log"})

# Public: `no_fstring_in_log._chain_has_getlogger` must test the SAME set with
# the SAME casing, or a factory can be a logger to one and not the other.
LOGGER_FACTORIES = frozenset({"getlogger", "get_logger"})
_LOGGER_FACTORIES = LOGGER_FACTORIES

# Shared by SARJ012 and SARJ017 so security and style sinks cannot drift apart.
LOG_METHODS = frozenset(
    {
        "critical",
        "debug",
        "error",
        "exception",
        "fatal",
        "info",
        "log",
        "success",
        "trace",
        "warn",
        "warning",
    }
)


def is_logger_expr(expr: ast.expr) -> bool:
    """Report whether `expr` evaluates to a logger."""
    if isinstance(expr, ast.Name):
        return expr.id.lower() in _LOGGER_NAMES
    if isinstance(expr, ast.Attribute):
        if expr.attr.lower() in _LOGGER_NAMES or expr.attr.lower() in _LOGGER_FACTORIES:
            return True
        return is_logger_expr(expr.value)
    if isinstance(expr, ast.Call):
        # A factory names a logger only when it is *called*: `get_logger()` is a
        callee = expr.func
        if isinstance(callee, ast.Attribute) and callee.attr.lower() in _LOGGER_FACTORIES:
            return True
        if isinstance(callee, ast.Name) and callee.id.lower() in _LOGGER_FACTORIES:
            return True
        return is_logger_expr(callee)
    return False
