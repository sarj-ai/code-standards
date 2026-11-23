from __future__ import annotations

import ast


_LOGGER_NAMES = frozenset({"logger", "log", "logging", "loguru", "_logger", "_log"})

LOGGER_FACTORIES = frozenset({"getlogger", "get_logger"})
_LOGGER_FACTORIES = LOGGER_FACTORIES

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
    match expr:
        case ast.Name(id=name):
            return name.lower() in _LOGGER_NAMES
        case ast.Attribute(value=value, attr=attr):
            if attr.lower() in _LOGGER_NAMES or attr.lower() in _LOGGER_FACTORIES:
                return True
            return is_logger_expr(value)
        case ast.Call(func=callee):
            match callee:
                case ast.Attribute() if callee.attr.lower() in _LOGGER_FACTORIES:
                    return True
                case ast.Name() if callee.id.lower() in _LOGGER_FACTORIES:
                    return True
                case _:
                    pass
            return is_logger_expr(callee)
        case _:
            return False
