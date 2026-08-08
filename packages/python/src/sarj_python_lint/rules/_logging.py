"""Shared logging-receiver detection for SARJ012/SARJ017."""

from __future__ import annotations

import ast


_LOGGER_NAMES = frozenset({"logger", "log", "logging", "loguru", "_logger", "_log"})

# Keep both rules on one normalized factory set so security cannot miss a receiver style lint sees.
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
    match expr:
        case ast.Name(id=name):
            return name.lower() in _LOGGER_NAMES
        case ast.Attribute(value=value, attr=attr):
            if attr.lower() in _LOGGER_NAMES or attr.lower() in _LOGGER_FACTORIES:
                return True
            return is_logger_expr(value)
        case ast.Call(func=callee):
            # A factory name denotes a logger only when called; otherwise it is merely a function.
            if isinstance(callee, ast.Attribute) and callee.attr.lower() in _LOGGER_FACTORIES:
                return True
            if isinstance(callee, ast.Name) and callee.id.lower() in _LOGGER_FACTORIES:
                return True
            return is_logger_expr(callee)
        case _:
            return False
