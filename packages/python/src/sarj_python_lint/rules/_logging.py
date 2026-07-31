"""Shared logging-receiver detection for SARJ012/SARJ017.

A single resolver for "does this receiver expression evaluate to a logger?",
used by both the secret-in-log and f-string-in-log rules so they recognise the
same factory/builder forms.
"""

from __future__ import annotations

import ast


_LOGGER_NAMES = frozenset({"logger", "log", "logging", "loguru", "_logger", "_log"})

# Public: `no_fstring_in_log._chain_has_getlogger` must test the SAME set with
# the SAME casing, or a factory can be a logger to one and not the other.
LOGGER_FACTORIES = frozenset({"getlogger", "get_logger"})
_LOGGER_FACTORIES = LOGGER_FACTORIES


def is_logger_expr(expr: ast.expr) -> bool:
    """Report whether `expr` evaluates to a logger.

    Resolves the whole receiver chain so adapter/builder/factory calls are
    caught: `logger.bind(...).info(...)`, `logger.opt(lazy=True).debug(...)`,
    `logging.getLogger(__name__).info(...)`, `self.logger.error(...)`, and the
    bare-name factory `get_logger().info(...)`.

    """
    if isinstance(expr, ast.Name):
        return expr.id.lower() in _LOGGER_NAMES
    if isinstance(expr, ast.Attribute):
        if expr.attr.lower() in _LOGGER_NAMES or expr.attr.lower() in _LOGGER_FACTORIES:
            return True
        return is_logger_expr(expr.value)
    if isinstance(expr, ast.Call):
        # A factory names a logger only when it is *called*: `get_logger()` is a
        # logger, the bare name `get_logger` is a function — which is why the
        # factories live in their own set and not in `_LOGGER_NAMES`. Both the
        # dotted spelling (`structlog.get_logger()`, `logging.getLogger()`) and
        # the bare one (`from structlog import get_logger`, then `get_logger()`)
        # have to be recognised right here: a bare callee is an `ast.Name`, and
        # recursing on it lands in the `_LOGGER_NAMES` branch, which by that
        # design does not carry the factory names. Omitting this second check is
        # a silent false negative rather than a crash, so it went unnoticed —
        # `get_logger().info("auth", token=token)`, structlog's own documented
        # module-level idiom, was unlinted by both SARJ012 and SARJ017.
        callee = expr.func
        if isinstance(callee, ast.Attribute) and callee.attr.lower() in _LOGGER_FACTORIES:
            return True
        if isinstance(callee, ast.Name) and callee.id.lower() in _LOGGER_FACTORIES:
            return True
        return is_logger_expr(callee)
    return False
